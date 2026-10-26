import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import pytest
from app import app, db
from integration_models import IntegrationGrant, TipPreview, TipReceipt
from models import TipEntry

ROOT = '/api/integrations/v1'


def headers(user='alice', key=None):
    result = {'Authorization': f'Bearer {user}', 'X-Integration-Client': 'test-client'}
    if key:
        result['Idempotency-Key'] = key
    return result


def entry(**changes):
    result = dict(work_date=datetime.now(ZoneInfo('America/New_York')).date().isoformat(),
                  section='Patio', cash_tips='20.25', card_tips='80.75', tip_out='0.00',
                  sales_amount='600.00', hours_worked='5.00', comments='Synthetic entry')
    result.update(changes)
    return result


def preview(client, user='alice', **changes):
    return client.post(ROOT + '/tip-previews', json=entry(**changes), headers=headers(user))


def create(client, record, key='test-key', user='alice'):
    return client.post(ROOT + '/tips', json={'preview_id': record['preview_id'], 'entry': record['entry']},
                       headers=headers(user, key))


def test_default_and_browser_cookie_cannot_authenticate(client):
    app.config['INTEGRATIONS_ENABLED'] = False
    assert client.get(ROOT + '/tips', headers=headers()).status_code == 404
    app.config['INTEGRATIONS_ENABLED'] = True
    with client.session_transaction() as session:
        session['user'] = {'id': 'alice'}
    assert client.get(ROOT + '/tips?demo=true').status_code == 401
    assert client.get(ROOT + '/tips', headers=headers('invalid')).status_code == 401


@pytest.mark.parametrize('field,value,status', [
    ('revoked', True, 401), ('expires_at', 1, 401), ('audience', 'wrong', 401),
    ('client_id', 'wrong', 401), ('scopes', 'tips:create', 403),
])
def test_credentials(client, field, value, status):
    with app.app_context():
        setattr(db.session.get(IntegrationGrant, 'alice'), field, value)
        db.session.commit()
    assert client.get(ROOT + '/tips', headers=headers()).status_code == status


@pytest.mark.parametrize('change', [
    {'cash_tips': True}, {'cash_tips': '-1'}, {'cash_tips': 'NaN'}, {'card_tips': 'Infinity'},
    {'cash_tips': '1.001'}, {'hours_worked': '0'}, {'hours_worked': '24.01'},
    {'sales_amount': '100000000.00'}, {'work_date': '2026-02-30'}, {'work_date': '20260101'},
    {'work_date': '9999-01-01'}, {'comments': 'x' * 501}, {'section': 'x' * 51},
    {'comments': 1}, {'user_id': 'bob'}, {'total_tips': 1}, {'cash_owed': '30.00'},
    {'cash_tips': '99999999.99', 'card_tips': '1.00'},
    {'cash_tips': '1000000', 'hours_worked': '0.01'},
    {'cash_tips': '999', 'sales_amount': '0.01'},
])
def test_invalid_fields(client, change):
    assert preview(client, **change).status_code == 400


@pytest.mark.parametrize('body', ['[]', 'null', '{', '{"cash_tips":NaN}', '{"x":1,"x":2}'])
def test_strict_json(client, body):
    assert client.post(ROOT + '/tip-previews', data=body, content_type='application/json', headers=headers()).status_code == 400


def test_unknown_and_tip_out(client):
    response = preview(client, cash_tips=None)
    assert response.status_code == 422
    assert response.json['preview_id'] is None
    assert 'cash_tips' in response.json['unresolved_fields']
    response = preview(client, tip_out=None)
    assert response.status_code == 422
    assert 'tip_out' in response.json['unresolved_fields']
    response = client.post(ROOT + '/tip-previews', json={'work_date': '2026-01-01'}, headers=headers())
    assert response.status_code == 422
    assert 'cash_tips' in response.json['unresolved_fields']


def test_preview_create_read_and_isolation(client):
    record = preview(client).json
    assert record['totals'] == dict(total_tips='101.00', net_tips='101.00', tips_per_hour='20.20', tip_percentage='16.83')
    with app.app_context():
        assert TipEntry.query.count() == 0
    response = create(client, record)
    assert response.status_code == 201
    tip_id = response.json['tip_entry']['id']
    assert client.get(f'{ROOT}/tips/{tip_id}', headers=headers()).json['tip_entry'] == response.json['tip_entry']
    assert client.get(f'{ROOT}/tips/{tip_id}', headers=headers('bob')).status_code == 404
    assert client.get(ROOT + '/tips', headers=headers('bob')).json['tips'] == []
    assert client.get(ROOT + '/sections', headers=headers('bob')).json['sections'] == []
    bob_record = preview(client, 'bob').json
    assert create(client, bob_record, 'bob-key', 'bob').status_code == 201
    # Alice is a manager, but sees only her own row.
    assert len(client.get(ROOT + '/tips', headers=headers()).json['tips']) == 1
    assert client.get(ROOT + '/sections', headers=headers()).json == {'sections': ['patio']}
    assert preview(client).json['possible_duplicates']
    assert create(client, preview(client).json, 'second-shift').status_code == 201


def test_changed_expired_and_consumed_previews(client):
    record = preview(client).json
    changed = {**record, 'entry': {**record['entry'], 'cash_tips': '1.00'}}
    assert create(client, changed).status_code == 409
    numeric = {**record, 'entry': {**record['entry'], 'cash_tips': 20.25}}
    assert create(client, numeric).status_code == 400
    assert create(client, record, user='bob').status_code == 409
    with app.app_context():
        db.session.get(TipPreview, record['preview_id']).expires_at = 1
        db.session.commit()
    assert create(client, record).status_code == 409
    record = preview(client).json
    assert create(client, record).status_code == 201
    assert create(client, record, 'other-key').status_code == 409


def test_idempotency_and_lost_response(client):
    record = preview(client).json
    first = create(client, record)
    assert first.status_code == 201
    with app.app_context():
        db.session.get(TipPreview, record['preview_id']).expires_at = 1
        db.session.commit()
    repeat = create(client, record)
    assert repeat.status_code == 200
    assert repeat.json['tip_entry']['id'] == first.json['tip_entry']['id']
    assert create(client, preview(client, cash_tips='1').json).status_code == 409
    with app.app_context():
        assert TipEntry.query.count() == TipReceipt.query.count() == 1


def test_pagination_and_creation_gate(client):
    record = preview(client).json
    app.config['INTEGRATIONS_CREATE_ENABLED'] = False
    assert create(client, record).status_code == 403
    app.config['INTEGRATIONS_CREATE_ENABLED'] = True
    assert create(client, record).status_code == 201
    assert create(client, preview(client).json, 'second').status_code == 201
    first = client.get(ROOT + '/tips?limit=1', headers=headers()).json
    second = client.get(ROOT + '/tips?limit=1&offset=1', headers=headers()).json
    assert first['next_offset'] == 1
    assert first['tips'][0]['id'] > second['tips'][0]['id']
    for args in ['limit=101', 'offset=-1', 'limit=no', 'user_id=bob', 'start_date=2026-13-01', 'start_date=2026-02-01&end_date=2026-01-01']:
        assert client.get(ROOT + '/tips?' + args, headers=headers()).status_code == 400


def test_browser_compatibility_and_exact_rounding(client):
    with client.session_transaction() as session:
        session['user'] = dict(id='alice', email='alice@example.invalid', name='alice')
    response = client.post('/api/tips', json=entry(cash_tips='0.10', card_tips='0.20', hours_worked='1'))
    assert response.status_code == 201
    assert response.json['tip_entry']['total_tips'] == 0.3
    assert client.get('/api/tips').status_code == 200
    assert client.get('/api/tips?demo=true').status_code == 200


def test_concurrent_same_preview(client, tmp_path):
    # File-backed SQLite permits separate connections. PostgreSQL remains a rollout gate.
    from sqlalchemy import create_engine
    engine = create_engine('sqlite:///' + str(tmp_path / 'concurrent.db'), connect_args={'timeout': 10})
    with app.app_context():
        old = db.engines[None]
        db.engines[None] = engine
        db.create_all()
        from models import User
        import hashlib
        db.session.add(User(id='alice', email='alice@example.invalid', name='alice', role='manager'))
        db.session.flush()
        db.session.add(IntegrationGrant(id='alice', token_hash=hashlib.sha256(b'alice').hexdigest(), user_id='alice',
            client_id='test-client', audience='tiptracker-integrations-v1', scopes='tips:read tips:create', expires_at=int(time.time()) + 3600))
        db.session.commit()
    try:
        record = preview(client).json
        def send(_):
            with app.test_client() as worker:
                return create(worker, record).status_code
        with ThreadPoolExecutor(max_workers=4) as pool:
            statuses = list(pool.map(send, range(4)))
        assert statuses.count(201) == 1
        assert statuses.count(200) == 3
        with app.app_context():
            assert TipEntry.query.count() == TipReceipt.query.count() == 1
    finally:
        with app.app_context():
            db.session.remove()
            db.engines[None] = old
        engine.dispose()


def test_create_requires_scope_and_exact_envelope(client):
    record = preview(client).json
    with app.app_context():
        db.session.get(IntegrationGrant, 'alice').scopes = 'tips:read'
        db.session.commit()
    assert preview(client).status_code == 403
    assert create(client, record).status_code == 403
    with app.app_context():
        db.session.get(IntegrationGrant, 'alice').scopes = 'tips:read tips:create'
        db.session.commit()
    assert client.post(ROOT + '/tips', json={'confirmed': True, 'entry': record['entry']}, headers=headers(key='a')).status_code == 400
    assert client.post(ROOT + '/tips', json={'preview_id': record['preview_id'], 'entry': record['entry']}, headers=headers()).status_code == 400


def test_body_limit_and_no_sensitive_audit(client, caplog):
    import logging
    with caplog.at_level(logging.INFO):
        response = preview(client)
    assert response.headers['Cache-Control'] == 'no-store'
    assert response.headers['X-Request-ID']
    logs = '\n'.join(record.message for record in caplog.records)
    assert 'integration_request request=' in logs
    assert 'Bearer alice' not in logs
    assert 'Synthetic entry' not in logs
    assert client.post(ROOT + '/tip-previews', data='x' * 17000, content_type='application/json', headers=headers()).status_code == 413


def test_automatic_fallback_rejected(client):
    app.config['INTEGRATIONS_DB_READY'] = False
    try:
        assert client.get(ROOT + '/tips', headers=headers()).status_code == 503
    finally:
        app.config['INTEGRATIONS_DB_READY'] = True


def test_shared_postgres_rounding():
    from tip_domain import calculate_totals
    assert calculate_totals('1.005', '0', '1', '0')['total_tips'] == __import__('decimal').Decimal('1.01')


@pytest.mark.parametrize('tip_out,net,hourly', [('15.00', '86.00', '17.20'), ('110.00', '-9.00', '-1.80')])
def test_tip_out_preview_create_and_read(client, tip_out, net, hourly):
    record = preview(client, tip_out=tip_out).json
    assert record['totals'] == dict(total_tips='101.00', net_tips=net, tips_per_hour=hourly, tip_percentage='16.83')
    response = create(client, record)
    assert response.status_code == 201
    saved = response.json['tip_entry']
    assert saved['tip_out'] == tip_out
    assert saved['net_tips'] == net
    assert saved['tips_per_hour'] == hourly
    assert create(client, record).json['tip_entry'] == saved
    changed = {**record, 'entry': {**record['entry'], 'tip_out': '1.00'}}
    assert create(client, changed, 'changed').status_code == 409


@pytest.mark.parametrize('value', [True, '-1', 'NaN', '1.001', '100000000.00'])
def test_invalid_tip_out(client, value):
    assert preview(client, tip_out=value).status_code == 400


def test_database_errors_are_generic(client, monkeypatch):
    from sqlalchemy.exc import SQLAlchemyError
    import integrations
    def broken(*args, **kwargs):
        raise SQLAlchemyError('private connection details')
    monkeypatch.setattr(integrations, 'own_tips', broken)
    response = client.get(ROOT + '/tips', headers=headers())
    assert response.status_code == 503
    assert response.json['error'] == 'Database operation failed'
    assert 'private' not in response.get_data(as_text=True)


def test_legacy_nullable_sales_are_not_invented(client):
    with app.app_context():
        tip = TipEntry(user_id='alice', work_date=datetime.now().date(), weekday=0,
                       cash_tips=1, card_tips=2, tip_out=0, hours_worked=1, sales_amount=0)
        db.session.add(tip)
        db.session.flush()
        tip.sales_amount = None
        tip.tip_percentage = None
        # Production permits historical NULL sales and percentage columns.
        from integrations import serialize
        result = serialize(tip)
        assert result['sales_amount'] is None
        assert result['tip_percentage'] is None
