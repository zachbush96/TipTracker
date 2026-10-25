"""Block outbound traffic before application import. Use only synthetic SQLite data."""
import os
import socket
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
os.environ['DATABASE_URL'] = 'sqlite://'
os.environ['DATABASE_URL_FALLBACK'] = ''
os.environ['SUPABASE_URL'] = ''
os.environ['SUPABASE_ANON_KEY'] = ''
os.environ['SESSION_SECRET'] = 'synthetic-tests-only'
os.environ['INTEGRATIONS_ENABLED'] = '0'
os.environ['INTEGRATIONS_CREATE_ENABLED'] = '0'


def no_network(*args, **kwargs):
    raise AssertionError('Outbound access is prohibited in tests')

socket.socket.connect = no_network
socket.create_connection = no_network

import pytest
from app import app, db
from models import User
from integration_models import IntegrationGrant
import hashlib
import time


@pytest.fixture
def client():
    app.config.update(TESTING=True, INTEGRATIONS_ENABLED=True, INTEGRATIONS_CREATE_ENABLED=True)
    with app.app_context():
        assert db.engine.url.drivername == 'sqlite' and db.engine.url.database in ('', None, ':memory:')
        db.drop_all()
        db.create_all()
        for name in ['alice', 'bob']:
            db.session.add(User(id=name, email=f'{name}@example.invalid', name=name,
                                role='manager' if name == 'alice' else 'server'))
        db.session.flush()
        for name in ['alice', 'bob']:
            db.session.add(IntegrationGrant(id=name, token_hash=hashlib.sha256(name.encode()).hexdigest(),
                user_id=name, client_id='test-client', audience='tiptracker-integrations-v1',
                scopes='tips:read tips:create', expires_at=int(time.time()) + 3600))
        db.session.commit()
    yield app.test_client()
    with app.app_context():
        db.session.remove()
        db.drop_all()
