"""Disposable localhost-only PostgreSQL contract checks; never uses app secrets."""
import hashlib
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
url = make_url(os.environ['TEST_POSTGRES_URL'])
if url.host not in ('localhost', '127.0.0.1') or url.database != 'tiptracker_test':
    raise RuntimeError('Only the disposable localhost tiptracker_test database is allowed')
# Import with an empty SQLite database, then explicitly swap the test engine.
os.environ.update(DATABASE_URL='sqlite://', DATABASE_URL_FALLBACK='',
                  SUPABASE_URL='', SUPABASE_REST_URL='', SUPABASE_ANON_KEY='', SESSION_SECRET='synthetic-tests-only')
from app import app, db
from integration_models import IntegrationGrant
from models import TipEntry

engine = create_engine(url.set(drivername='postgresql+psycopg2'))
with engine.begin() as conn:
    # Dedicated CI database; fail if it is not empty instead of dropping anything.
    assert conn.scalar(text("select count(*) from information_schema.tables where table_schema='public'")) == 0
    conn.exec_driver_sql("create schema auth; create table auth.users (id uuid primary key)")
    conn.exec_driver_sql("create function auth.uid() returns uuid language sql stable as $$ select nullif(current_setting('request.jwt.claim.sub', true), '')::uuid $$")
    conn.exec_driver_sql('create role anon; create role authenticated')
    conn.exec_driver_sql((ROOT / 'schema.sql').read_text())
    conn.exec_driver_sql('alter default privileges in schema public grant all on tables to anon, authenticated')
    conn.exec_driver_sql((ROOT / 'integration_schema.sql').read_text())
    for name, uid in [('alice', '00000000-0000-0000-0000-000000000001'),
                      ('bob', '00000000-0000-0000-0000-000000000002')]:
        conn.execute(text('insert into auth.users values (:id)'), {'id': uid})
        conn.execute(text("insert into public.users(id,email,name,role) values (:id,:email,:name,:role)"),
                     dict(id=uid, email=name+'@example.invalid', name=name,
                          role='manager' if name == 'alice' else 'server'))

app.config.update(TESTING=True, INTEGRATIONS_ENABLED=True,
                  INTEGRATIONS_CREATE_ENABLED=True, INTEGRATIONS_DB_READY=True)
with app.app_context():
    db.engines[None] = engine
    for name, uid in [('alice', '00000000-0000-0000-0000-000000000001'),
                      ('bob', '00000000-0000-0000-0000-000000000002')]:
        db.session.add(IntegrationGrant(id=name, token_hash=hashlib.sha256(name.encode()).hexdigest(),
            user_id=uid, client_id='synthetic', audience='tiptracker-integrations-v1',
            scopes='tips:read tips:create', expires_at=int(time.time())+3600))
    db.session.commit()

API = '/api/integrations/v1'
def headers(name='alice', key=None):
    result = {'Authorization': 'Bearer '+name, 'X-Integration-Client': 'synthetic'}
    if key:
        result['Idempotency-Key'] = key
    return result

entry = dict(work_date=datetime.now(ZoneInfo('America/New_York')).date().isoformat(), section='Patio', cash_tips='20.25',
             card_tips='80.75', tip_out='15.00', hours_worked='5.00', sales_amount='600.00',
             comments='Synthetic PostgreSQL contract test')
client = app.test_client()
assert client.get(API+'/tips').status_code == 401
bad = client.post(API+'/tip-previews', json={**entry, 'tip_out': None}, headers=headers())
assert bad.status_code == 422
record = client.post(API+'/tip-previews', json=entry, headers=headers()).json
assert record['totals'] == dict(total_tips='101.00', net_tips='86.00', tips_per_hour='17.20', tip_percentage='16.83')
body = dict(preview_id=record['preview_id'], entry=record['entry'])
assert client.post(API+'/tips', json=body, headers=headers('bob', 'cross-owner')).status_code == 409
assert client.post(API+'/tips', json={**body, 'entry': {**body['entry'], 'tip_out':'1.00'}}, headers=headers(key='changed')).status_code == 409

def send(_):
    with app.test_client() as worker:
        return worker.post(API+'/tips', json=body, headers=headers(key='retry'))
with ThreadPoolExecutor(max_workers=4) as pool:
    responses = list(pool.map(send, range(4)))
assert sorted(r.status_code for r in responses) == [200, 200, 200, 201]
saved = responses[0].json['tip_entry']
assert saved['tip_out'] == '15.00' and saved['net_tips'] == '86.00'
assert saved['tips_per_hour'] == record['totals']['tips_per_hour']
assert client.get(API+'/tips', headers=headers('bob')).json['tips'] == []
assert client.get(API+'/tips/'+str(saved['id']), headers=headers('bob')).status_code == 404
assert client.get(API+'/tips', headers=headers()).json['tips'] == [saved]
with app.app_context():
    assert TipEntry.query.count() == 1
    db.session.remove()

# Server-only tables are inaccessible even with Supabase-like default table grants.
with engine.begin() as conn:
    for table in ('integration_grants', 'integration_tip_previews', 'integration_tip_receipts'):
        assert conn.scalar(text('select relrowsecurity from pg_class where oid=to_regclass(:table)'), {'table':table})
        for role in ('anon', 'authenticated'):
            for privilege in ('SELECT', 'INSERT', 'UPDATE', 'DELETE', 'TRUNCATE'):
                assert not conn.scalar(text('select has_table_privilege(:role,:table,:privilege)'),
                    dict(role=role, table=table, privilege=privilege))
    conn.exec_driver_sql('grant usage on schema public, auth to authenticated; grant execute on function auth.uid() to authenticated; grant select on public.tip_entries to authenticated')
    conn.exec_driver_sql('set local role authenticated')
    conn.exec_driver_sql("select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000002',true)")
    assert conn.scalar(text('select count(*) from public.tip_entries')) == 0
    conn.exec_driver_sql("select set_config('request.jwt.claim.sub','00000000-0000-0000-0000-000000000001',true)")
    assert conn.scalar(text('select count(*) from public.tip_entries')) == 1
print('PostgreSQL UUID/FK schema, trigger totals, owner isolation, preview integrity, concurrent retries, and server-only RLS/grants passed')

# New self-service grants use the same UUID-backed schema, without extra tables.
from types import SimpleNamespace
import integration_access
integration_access.get_supabase_client = lambda: SimpleNamespace(auth=SimpleNamespace(
    get_user=lambda token: SimpleNamespace(user=SimpleNamespace(id='00000000-0000-0000-0000-000000000001'))))
app.config['INTEGRATIONS_SELF_SERVICE_ENABLED'] = True
app.secret_key = 'synthetic-postgres-consent-test-only-' * 2
with client.session_transaction() as cookie:
    cookie['user'] = dict(id='untrusted-cookie-id', access_token='synthetic-login')
consent = client.get('/api/integration-access').json
consent_body = dict(client_id='rook', expires_in_hours=24, consent=consent['consent'], issuance_id=consent['issuance_id'])
consent_headers = {'Origin':'http://localhost', 'X-CSRF-Token':consent['csrf_token']}
cookie_value = client.get_cookie(app.config['SESSION_COOKIE_NAME']).value
def issue_read(_):
    with app.test_client() as worker:
        worker.set_cookie(app.config['SESSION_COOKIE_NAME'], cookie_value)
        return worker.post('/api/integration-access/grants', json=consent_body, headers=consent_headers)
with ThreadPoolExecutor(max_workers=4) as pool:
    issued = list(pool.map(issue_read, range(4)))
assert sorted(r.status_code for r in issued) == [201, 409, 409, 409]
grant = next(r.json for r in issued if r.status_code == 201)
assert grant['scopes'] == ['tips:read']
read_headers = {'Authorization': 'Bearer '+grant['token'], 'X-Integration-Client':'rook'}
assert len(client.get(API+'/tips', headers=read_headers).json['tips']) == 1
assert client.post(API+'/tip-previews', json=entry, headers=read_headers).status_code == 403
assert 'token_hash' not in client.get('/api/integration-access').get_data(as_text=True)
consent = client.get('/api/integration-access').json
revoked = client.post('/api/integration-access/grants/'+grant['id']+'/revoke', json={'revoke':True},
    headers={'Origin':'http://localhost', 'X-CSRF-Token':consent['csrf_token']})
assert revoked.status_code == 200
assert client.get(API+'/tips', headers=read_headers).status_code == 401
print('PostgreSQL self-service concurrent one-time issuance, read-only scope and immediate revocation passed')
engine.dispose()
