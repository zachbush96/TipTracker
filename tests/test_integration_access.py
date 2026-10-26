import hashlib
import logging
import time
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
import integration_access
from integration_access import AuthApiError
from app import app, db
from integration_models import IntegrationGrant
from models import TipEntry, User

ROOT = '/api/integration-access'


def sign_in(client, name='alice', claimed_id=None):
    with client.session_transaction() as cookie:
        cookie.clear()
        cookie['user'] = dict(id=claimed_id or name, access_token='login-' + name)


@pytest.fixture
def access(client, monkeypatch):
    monkeypatch.setitem(app.config, 'INTEGRATIONS_SELF_SERVICE_ENABLED', True)
    monkeypatch.setattr(app, 'secret_key', 'isolated-management-tests-only-' * 2)
    calls = []

    def get_user(token):
        calls.append(token)
        if token == 'login-expired':
            raise AuthApiError('Synthetic expired token', 401, 'bad_jwt')
        if token == 'login-outage':
            raise RuntimeError('private credential details must not appear')
        name = token.removeprefix('login-')
        return SimpleNamespace(user=SimpleNamespace(id=name))

    monkeypatch.setattr(integration_access, 'get_supabase_client',
                        lambda: SimpleNamespace(auth=SimpleNamespace(get_user=get_user)))
    sign_in(client)
    return client, calls


def state(client):
    response = client.get(ROOT)
    assert response.status_code == 200
    return response.json


def body(record, **changes):
    return dict(client_id='rook', expires_in_hours=24, access='read', consent=record['consents']['read'],
                issuance_id=record['issuance_id'], **changes)


def headers(record, **changes):
    return {'Origin': 'http://localhost', 'X-CSRF-Token': record['csrf_token'], **changes}


def issue(client, record=None, **changes):
    record = record or state(client)
    payload = body(record)
    if changes.get('access') in record['consents'] and 'consent' not in changes:
        payload['consent'] = record['consents'][changes['access']]
    payload.update(changes)
    return client.post(ROOT + '/grants', json=payload, headers=headers(record))


def revoke(client, grant_id, record=None):
    record = record or state(client)
    return client.post(ROOT + f'/grants/{grant_id}/revoke', json={'revoke': True}, headers=headers(record))


def test_management_defaults_disabled(client):
    assert client.get('/integrations').status_code == 404
    assert client.get(ROOT).status_code == 404
    assert client.post(ROOT + '/grants').status_code == 404


def test_both_feature_flags_and_database_gate(access, monkeypatch):
    client, _ = access
    monkeypatch.setitem(app.config, 'INTEGRATIONS_ENABLED', False)
    assert client.get(ROOT).status_code == 404
    monkeypatch.setitem(app.config, 'INTEGRATIONS_ENABLED', True)
    monkeypatch.setitem(app.config, 'INTEGRATIONS_DB_READY', False)
    assert client.get(ROOT).status_code == 503


def test_weak_session_secret_rejected(access, monkeypatch):
    client, _ = access
    monkeypatch.setattr(app, 'secret_key', 'dev-secret-key-change-in-production')
    # A known development default is not a valid management secret.
    assert client.get(ROOT).status_code == 503


@pytest.mark.parametrize('name,status', [('expired', 401), ('outage', 503), ('missing', 403)])
def test_fresh_verification_failures(access, name, status):
    client, calls = access
    sign_in(client, name)
    response = client.get(ROOT)
    assert response.status_code == status
    assert calls == ['login-' + name]
    assert 'private credential' not in response.get_data(as_text=True)


def test_cookies_without_verified_access_token_do_not_authenticate(access):
    client, _ = access
    with client.session_transaction() as cookie:
        cookie['user'] = {'id': 'alice', 'role': 'manager'}
    assert client.get(ROOT).status_code == 401


def test_fresh_subject_overrides_claimed_cookie_identity(access):
    client, calls = access
    sign_in(client, 'alice', claimed_id='bob')
    response = issue(client)
    assert response.status_code == 201
    with app.app_context():
        assert db.session.get(IntegrationGrant, response.json['id']).user_id == 'alice'
    assert len(calls) == 2  # verification for consent state AND issuance


def test_issue_read_scope_once_and_revoke(access, caplog):
    client, calls = access
    record = state(client)
    before = int(time.time())
    with caplog.at_level(logging.INFO):
        response = issue(client, record)
    assert response.status_code == 201
    result = response.json
    token = result['token']
    assert len(token) >= 50
    assert result['scopes'] == ['tips:read']
    assert before + 86400 <= result['expires_at'] <= int(time.time()) + 86400
    digest = hashlib.sha256(token.encode()).hexdigest()
    with app.app_context():
        grant = db.session.get(IntegrationGrant, result['id'])
        assert grant.token_hash == digest
        assert grant.user_id == 'alice' and grant.audience == 'tiptracker-integrations-v1'
        for owner in ('alice', 'bob'):
            db.session.add(TipEntry(user_id=owner, cash_tips=10, card_tips=20, tip_out=5,
                hours_worked=5, sales_amount=100,
                work_date=datetime.now(ZoneInfo('America/New_York')).date(), weekday=0))
        db.session.commit()
    # The same issuance request is never retried into another token or redisplayed.
    replay = issue(client, record)
    assert replay.status_code == 409 and token not in replay.get_data(as_text=True)
    api_headers = {'Authorization': 'Bearer ' + token, 'X-Integration-Client': 'rook'}
    tips = client.get('/api/integrations/v1/tips', headers=api_headers)
    assert tips.status_code == 200 and len(tips.json['tips']) == 1
    assert client.post('/api/integrations/v1/tip-previews', json={}, headers=api_headers).status_code == 403
    assert client.post('/api/integrations/v1/tips', json={}, headers=api_headers).status_code == 403
    listing = state(client)
    text = str(listing)
    assert token not in text and digest not in text and 'token_hash' not in text
    assert token not in caplog.text and digest not in caplog.text and 'login-alice' not in caplog.text
    assert revoke(client, result['id'], listing).status_code == 200
    assert revoke(client, result['id']).status_code == 200
    assert client.get('/api/integrations/v1/tips', headers=api_headers).status_code == 401


def test_all_existing_users_have_own_connections_even_managers(access):
    client, _ = access
    alice = issue(client).json
    sign_in(client, 'bob')
    bob = issue(client).json
    assert bob['id'] != alice['id']
    assert {r['id'] for r in state(client)['connections']} == {'bob', bob['id']}
    assert revoke(client, alice['id']).status_code == 404
    sign_in(client, 'alice')  # Manager role grants no cross-account management rights.
    assert {r['id'] for r in state(client)['connections']} == {'alice', alice['id']}
    assert revoke(client, bob['id']).status_code == 404
    with app.app_context():
        assert not db.session.get(IntegrationGrant, bob['id']).revoked
        assert User.query.count() == 2


@pytest.mark.parametrize('changes', [
    {'user_id': 'bob'}, {'scopes': ['tips:create']}, {'audience': 'other'},
    {'expires_in_hours': True}, {'expires_in_hours': 48}, {'expires_in_hours': '24'},
    {'client_id': '<script>'}, {'client_id': 'a' * 65}, {'client_id': ''},
    {'token': 'choose-my-token'},
])
def test_client_cannot_expand_permissions(access, changes):
    client, _ = access
    assert issue(client, **changes).status_code == 400
    with app.app_context():
        assert IntegrationGrant.query.count() == 2


def test_explicit_consent_and_csrf_required(access):
    client, _ = access
    record = state(client)
    assert issue(client, record, consent=True).status_code == 403
    assert issue(client, record, issuance_id='someone-else').status_code == 403
    for patch in ({'Origin': 'https://other.invalid'}, {'Origin': ''},
                  {'X-CSRF-Token': ''}, {'X-CSRF-Token': 'é'}, {'Sec-Fetch-Site': 'cross-site'}):
        response = client.post(ROOT + '/grants', json=body(record), headers=headers(record, **patch))
        assert response.status_code == 403
    with client.session_transaction() as cookie:
        expired = dict(cookie[integration_access.SESSION_KEY]); expired['expires_at'] = 1
        cookie[integration_access.SESSION_KEY] = expired
    assert issue(client, record).status_code == 403


def test_short_expiry_and_wrong_client_rejected(access):
    client, _ = access
    result = issue(client, expires_in_hours=1).json
    assert result['expires_at'] <= int(time.time()) + 3600
    api = '/api/integrations/v1/tips'
    assert client.get(api, headers={'Authorization': 'Bearer ' + result['token'], 'X-Integration-Client': 'wrong'}).status_code == 401
    with app.app_context():
        db.session.get(IntegrationGrant, result['id']).expires_at = 1
        db.session.commit()
    assert client.get(api, headers={'Authorization': 'Bearer ' + result['token'], 'X-Integration-Client': 'rook'}).status_code == 401


def test_private_page_headers_and_no_external_scripts(access):
    client, _ = access
    response = client.get('/integrations')
    assert response.status_code == 200
    html = response.get_data(as_text=True)
    assert 'src="https://' not in html and 'href="https://' not in html
    assert 'localStorage' not in html and 'API token' in html
    assert 'other dates in your history' in html
    for route in ('/integrations', ROOT):
        response = client.get(route, headers={'Origin': 'https://other.invalid'})
        assert response.headers['Cache-Control'] == 'no-store'
        assert response.headers['Referrer-Policy'] == 'no-referrer'
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']
        if route == ROOT:
            assert 'Access-Control-Allow-Origin' not in response.headers
    preflight = client.options(ROOT + '/grants', headers={
        'Origin': 'https://other.invalid', 'Access-Control-Request-Method': 'POST'})
    assert 'Access-Control-Allow-Origin' not in preflight.headers


def test_storage_errors_do_not_leak_details(access, monkeypatch):
    client, _ = access
    from sqlalchemy.exc import SQLAlchemyError
    def unavailable(*args, **kwargs):
        raise SQLAlchemyError('private database URL')
    monkeypatch.setattr(db.session, 'get', unavailable)
    response = client.get(ROOT)
    assert response.status_code == 503
    assert 'private database' not in response.get_data(as_text=True)


def test_read_create_requires_its_own_consent_and_feature_gate(access, monkeypatch):
    client, _ = access
    record = state(client)
    assert issue(client, record, access='read-create', consent=record['consents']['read']).status_code == 403
    monkeypatch.setitem(app.config, 'INTEGRATIONS_CREATE_ENABLED', False)
    assert state(client)['create_enabled'] is False
    assert issue(client, access='read-create').status_code == 403
    assert issue(client).status_code == 201


@pytest.mark.parametrize('owner', ['alice', 'bob'])
def test_self_service_read_create_preview_confirmation_and_retry(access, owner):
    from test_integrations import entry
    client, _ = access
    sign_in(client, owner)
    credential = issue(client, access='read-create', client_id='codex').json
    assert credential['scopes'] == ['tips:read', 'tips:create']
    api_headers = {'Authorization': 'Bearer ' + credential['token'], 'X-Integration-Client': 'codex', 'Idempotency-Key': 'approved-once'}
    root = '/api/integrations/v1'
    proposed = client.post(root + '/tip-previews', json=entry(tip_out='15.00'), headers=api_headers)
    assert proposed.status_code == 200
    record = proposed.json
    assert record['consent_required'] is True and record['totals']['net_tips'] == '86.00'
    with app.app_context():
        assert TipEntry.query.count() == 0
    payload = dict(preview_id=record['preview_id'], entry=record['entry'])
    changed = {**payload, 'entry': {**payload['entry'], 'tip_out': '10.00'}}
    assert client.post(root + '/tips', json=changed, headers=api_headers).status_code == 409
    saved = client.post(root + '/tips', json=payload, headers=api_headers)
    assert saved.status_code == 201
    saved_id = saved.json['tip_entry']['id']
    replay = client.post(root + '/tips', json=payload, headers=api_headers)
    assert replay.status_code == 200 and replay.json['tip_entry']['id'] == saved_id
    assert client.get(root + '/tips/' + str(saved_id), headers=api_headers).status_code == 200
    with app.app_context():
        assert TipEntry.query.count() == 1
        assert TipEntry.query.one().user_id == owner
    assert revoke(client, credential['id']).status_code == 200
    assert client.post(root + '/tips', json=payload, headers=api_headers).status_code == 401


@pytest.mark.parametrize('value', ['admin', 'create', True, ['tips:read', 'tips:create']])
def test_access_level_is_a_fixed_enum(access, value):
    client, _ = access
    record = state(client)
    payload = body(record); payload['access'] = value
    assert client.post(ROOT + '/grants', json=payload, headers=headers(record)).status_code == 400
