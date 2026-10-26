"""Startup must not provision a database, even when its schema is absent."""
import os
import subprocess
import sys

from sqlalchemy import inspect

from app import app, db


def test_fresh_startup_does_not_issue_ddl_or_dml():
    # A new interpreter exercises import-time behavior, before fixture setup.
    script = '''
import socket
def no_network(*args, **kwargs):
    raise AssertionError('Network access is prohibited')
socket.socket.connect = no_network
socket.create_connection = no_network
from sqlalchemy import event, inspect
from sqlalchemy.engine import Engine
statements = []
event.listen(Engine, 'before_cursor_execute', lambda conn, cursor, statement, parameters, context, executemany: statements.append(statement))
from app import app, db
with app.app_context():
    assert inspect(db.engine).get_table_names() == []
    assert all(s.lstrip().upper().startswith(('SELECT', 'PRAGMA')) for s in statements), statements
    client = app.test_client()
    assert client.get('/healthz').status_code == 200
    assert client.get('/api/integrations/v1/tips').status_code == 404
    assert not app.config['INTEGRATIONS_ENABLED']
    assert not app.config['INTEGRATIONS_CREATE_ENABLED']
    assert not app.config['INTEGRATIONS_SELF_SERVICE_ENABLED']
'''
    env = {**os.environ, 'DATABASE_URL': 'sqlite://', 'DATABASE_URL_FALLBACK': '',
           'SUPABASE_URL': '', 'SUPABASE_REST_URL': '', 'SUPABASE_ANON_KEY': '',
           'SESSION_SECRET': 'synthetic-startup-test'}
    env.pop('INTEGRATIONS_ENABLED', None)
    env.pop('INTEGRATIONS_CREATE_ENABLED', None)
    env.pop('INTEGRATIONS_SELF_SERVICE_ENABLED', None)
    result = subprocess.run([sys.executable, '-c', script], env=env,
                            capture_output=True, text=True, timeout=20)
    assert result.returncode == 0, result.stdout + result.stderr


def test_explicit_development_setup_creates_only_browser_tables(client):
    with app.app_context():
        db.drop_all()
    result = app.test_cli_runner().invoke(args=['init-dev-db'])
    assert result.exit_code == 0, result.output
    with app.app_context():
        assert set(inspect(db.engine).get_table_names()) == {'users', 'tip_entries'}


def test_development_setup_rejects_production_and_automatic_fallback(client, monkeypatch):
    module = sys.modules['app']
    for uri in ('postgresql+psycopg2://localhost/unused', ''):
        monkeypatch.setattr(module, 'PRIMARY_DB_URI', uri)
        result = app.test_cli_runner().invoke(args=['init-dev-db'])
        assert result.exit_code != 0
        assert 'requires an explicit SQLite' in result.output
