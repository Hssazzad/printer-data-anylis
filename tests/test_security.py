"""Integration tests use a new disposable database on a local MySQL server."""
import hashlib
import json
import os
import subprocess
import sys
import uuid

import pymysql
import pytest
from fastapi.testclient import TestClient

import ai_service
import db.auth as auth
import db.connection as connection
import db.menus as menus
import db.users as users
import main


@pytest.fixture
def db(monkeypatch):
    if os.getenv('PRINTER_TEST_MYSQL') != '1':
        pytest.skip('set PRINTER_TEST_MYSQL=1 to use a disposable local MySQL server')
    host = os.getenv('DB_HOST', '127.0.0.1')
    port = int(os.getenv('DB_PORT', '3306'))
    user = os.getenv('DB_USER', 'root')
    password = os.getenv('DB_PASSWORD', '')
    name = 'printer_test_' + uuid.uuid4().hex
    admin = pymysql.connect(host=host, port=port, user=user, password=password, autocommit=True)
    with admin.cursor() as cur:
        cur.execute(f'CREATE DATABASE `{name}`')
    monkeypatch.setattr(connection, 'DB_HOST', host)
    monkeypatch.setattr(connection, 'DB_PORT', port)
    monkeypatch.setattr(connection, 'DB_USER', user)
    monkeypatch.setattr(connection, 'DB_PASSWORD', password)
    monkeypatch.setattr(connection, 'DB_NAME', name)
    monkeypatch.setattr(auth, '_auth_initialized', False)
    monkeypatch.setattr(menus, '_menus_initialized', False)
    auth.init_auth_system()
    menus.init_menus_table()
    yield {'DB_HOST': host, 'DB_PORT': str(port), 'DB_USER': user, 'DB_PASSWORD': password, 'DB_NAME': name}
    with admin.cursor() as cur:
        cur.execute(f'DROP DATABASE `{name}`')
    admin.close()


def sql(query, args=()):
    with connection.get_connection() as conn:
        with conn.cursor() as cur:
            cur.execute(query, args)
            rows = cur.fetchall() if cur.description else None
            conn.commit()
            return rows


def command(db, action, password):
    env = {**os.environ, **db, 'DASHBOARD_ADMIN_PASSWORD': password}
    return subprocess.run([sys.executable, 'manage_admin.py', action], env=env, capture_output=True, text=True)


def test_bootstrap_upgrade_and_reset(db):
    assert sql('SELECT * FROM dashboard_auth') == ()
    assert command(db, 'setup', 'admin').returncode != 0
    assert command(db, 'setup', 'new secure secret').returncode == 0
    assert command(db, 'setup', 'other secret').returncode != 0
    salt = 'legacy-salt'
    old_hash = hashlib.sha256((salt + 'old password').encode()).hexdigest()
    sql("INSERT INTO dashboard_auth (username,role,allowed_menus,password_salt,password_hash) VALUES ('legacy','Operator','[]',%s,%s)", (salt, old_hash))
    assert auth.authenticate_user('legacy', 'wrong') is None
    legacy = auth.authenticate_user('legacy', 'old password')
    assert legacy
    assert sql('SELECT password_hash FROM dashboard_auth WHERE id=%s', (legacy['id'],))[0]['password_hash'].startswith('$argon2')
    admin_id = sql("SELECT id FROM dashboard_auth WHERE username='admin'")[0]['id']
    old = sql('SELECT password_hash FROM dashboard_auth WHERE id=%s', (admin_id,))[0]['password_hash']
    token = auth.create_session(admin_id, old)
    default_hash = hashlib.sha256((salt + 'admin').encode()).hexdigest()
    sql("UPDATE dashboard_auth SET password_salt=%s,password_hash=%s WHERE username='admin'", (salt, default_hash))
    assert auth.create_session(admin_id, old) is None
    assert not auth.verify_session(token)
    assert auth.authenticate_user('admin', 'admin') is None
    assert command(db, 'reset', 'replacement secret').returncode == 0
    assert auth.authenticate_user('admin', 'replacement secret')
    assert not auth.verify_session(token)
    assert users.delete_dashboard_user(admin_id)
    assert command(db, 'setup', 'replacement administrator').returncode == 0
    assert auth.authenticate_user('legacy', 'old password')


def test_menu_seed_preservation_and_url_safety(db):
    rows = sql('SELECT id,parent_id,url FROM sidebar_menus ORDER BY id')
    assert len(rows) == 12
    assert len({r['id'] for r in rows}) == len(rows)
    ids = {r['id'] for r in rows}
    assert all(r['parent_id'] in ids for r in rows if r['parent_id'] is not None)
    sql('DELETE FROM sidebar_menus')
    sql("INSERT INTO sidebar_menus (title,url) VALUES ('custom','/custom')")
    menus._menus_initialized = False
    menus.init_menus_table()
    assert [r['title'] for r in sql('SELECT title FROM sidebar_menus')] == ['custom']
    for bad in ('javascript:alert(1)', '//evil.example/x', '/\\evil', 'https://[broken'):
        assert menus.safe_menu_url(bad) == '#'
        with pytest.raises(ValueError):
            menus.create_sidebar_menu({'title': 'bad', 'url': bad})
    payload = '<img src=x onerror=alert(1)>'
    sql("UPDATE sidebar_menus SET title=%s, url='javascript:alert(1)'", (payload,))
    stored = menus.get_sidebar_menus()[0]
    assert stored['title'] == payload
    assert stored['url'] == '#'


def test_authorization_and_revocation(db, monkeypatch):
    assert command(db, 'setup', 'secure administrator').returncode == 0
    peak_id = sql("SELECT id FROM sidebar_menus WHERE url='/peak-period'")[0]['id']
    restricted_id = users.create_dashboard_user({'username':'restricted', 'password':'restricted password', 'role':'Operator', 'allowed_menus':[peak_id]})
    full_id = users.create_dashboard_user({'username':'full', 'password':'full password', 'role':'Manager', 'allowed_menus':'*'})
    admin_id = sql("SELECT id FROM dashboard_auth WHERE username='admin'")[0]['id']
    def session(user_id):
        stored = sql('SELECT password_hash FROM dashboard_auth WHERE id=%s', (user_id,))[0]['password_hash']
        return auth.create_session(user_id, stored)
    tokens = {name: session(user_id) for name, user_id in [('restricted', restricted_id), ('full', full_id), ('admin', admin_id)]}
    monkeypatch.setattr(main.database, 'get_peak_timing_summary', lambda: {'ok': True})
    monkeypatch.setattr(main.database, 'get_affinity_overview', lambda: {'ok': True})
    monkeypatch.setattr(main.database, 'get_dashboard_kpis', lambda: {'ok': True})
    client = TestClient(main.app)
    login = client.post('/api/auth/login', json={'username':'restricted', 'password':'restricted password'})
    assert login.status_code == 200 and login.json()['redirect'] == '/peak-period'
    client.cookies.clear()
    assert client.get('/api/customer-affinity/overview').status_code == 401
    assert client.delete('/api/menus/1').status_code == 401
    assert client.get('/api/peak-timing', cookies={'session_token':tokens['restricted']}).status_code == 200
    for path in ('/api/customer-affinity/overview', '/api/stats', '/api/ai/insights', '/api/users', '/api/menus?all=true', '/menus/dashboard', '/menus/main'):
        method = client.post if path == '/api/ai/insights' else client.get
        assert method(path, cookies={'session_token':tokens['restricted']}).status_code == 403
    assert client.get('/api/customer-affinity/overview', cookies={'session_token':tokens['full']}).status_code == 200
    assert client.get('/api/users', cookies={'session_token':tokens['full']}).status_code == 403
    visible = client.get('/api/menus', cookies={'session_token':tokens['full']}).json()
    urls = {item['url'] for menu in visible for item in [menu, *menu['submenus']]}
    assert '/menus/main' not in urls and '/menus/sub' not in urls
    admin_visible = client.get('/api/menus', cookies={'session_token':tokens['admin']}).json()
    assert any(child['url'] == '/menus/main' for menu in admin_visible for child in menu['submenus'])
    assert client.get('/api/users', cookies={'session_token':tokens['admin']}).status_code == 200
    assert client.get('/', cookies={'session_token':tokens['restricted']}, follow_redirects=False).headers['location'] == '/peak-period'
    assert users.update_dashboard_user(restricted_id, {'username':'restricted','role':'Operator','allowed_menus':[peak_id],'password':'new password'})
    assert not auth.verify_session(tokens['restricted'])
    assert users.delete_dashboard_user(full_id)
    assert not auth.verify_session(tokens['full'])


def test_forecast_receives_24_months(monkeypatch):
    ai_service._CONTEXT_CACHE.update(data=None, ts=0)
    called = []
    monkeypatch.setattr(ai_service.database, 'get_monthly_sales_trend', lambda months: called.append(months) or [])
    for name in ('get_dashboard_kpis', 'get_top_selling_products', 'get_inventory_summary', 'get_top_customers', 'get_affinity_overview'):
        monkeypatch.setattr(ai_service.database, name, lambda **kwargs: {})
    ai_service.build_business_context()
    assert called == [24]


def test_username_uniqueness_migration_preserves_duplicates(db):
    sql('DROP INDEX uq_dashboard_auth_username ON dashboard_auth')
    sql("INSERT INTO dashboard_auth (username, password_salt, password_hash) VALUES ('duplicate', '', 'x'), ('duplicate', '', 'y')")
    auth._auth_initialized = False
    with pytest.raises(RuntimeError, match='Duplicate dashboard usernames'):
        auth.init_auth_system()
    assert len(sql("SELECT id FROM dashboard_auth WHERE username='duplicate'")) == 2
    sql("UPDATE dashboard_auth SET username='renamed' WHERE username='duplicate' ORDER BY id DESC LIMIT 1")
    auth.init_auth_system()
    with pytest.raises(pymysql.err.IntegrityError):
        users.create_dashboard_user({'username':'duplicate', 'password':'secret'})


def test_ambiguous_phone_login_is_rejected(db):
    users.create_dashboard_user({'username':'a', 'phone':'123', 'password':'one'})
    users.create_dashboard_user({'username':'b', 'phone':'123', 'password':'two'})
    assert auth.authenticate_user('123', 'one') is None
    assert auth.authenticate_user('a', 'one')


def test_new_user_defaults_and_update_preserves_role_and_permissions(db):
    user_id = users.create_dashboard_user({'username':'new-user', 'password':'secret'})
    row = sql('SELECT role, allowed_menus FROM dashboard_auth WHERE id=%s', (user_id,))[0]
    assert row['role'] == 'Operator' and json.loads(row['allowed_menus']) == []
    assert users.update_dashboard_user(user_id, {'username':'new-user'})
    row = sql('SELECT role, allowed_menus FROM dashboard_auth WHERE id=%s', (user_id,))[0]
    assert row['role'] == 'Operator' and json.loads(row['allowed_menus']) == []
    token = auth.create_session(user_id, sql('SELECT password_hash FROM dashboard_auth WHERE id=%s', (user_id,))[0]['password_hash'])
    client = TestClient(main.app)
    assert client.get('/api/users', cookies={'session_token':token}).status_code == 403
    assert client.get('/api/stats', cookies={'session_token':token}).status_code == 403
    admin_id = users.create_dashboard_user({'username':'another-admin', 'password':'secret', 'role':'Admin', 'allowed_menus':[]})
    admin_token = auth.create_session(admin_id, sql('SELECT password_hash FROM dashboard_auth WHERE id=%s', (admin_id,))[0]['password_hash'])
    assert client.get('/api/users', cookies={'session_token':admin_token}).status_code == 200


def test_legacy_empty_permissions_are_migrated_once(db):
    sql("DELETE FROM dashboard_migrations WHERE migration_key='explicit_menu_permissions_v1'")
    sql("INSERT INTO dashboard_auth (username,role,allowed_menus,password_salt,password_hash) VALUES ('legacy-empty','Operator',NULL,'',%s)", (auth.hash_password('secret'),))
    auth._auth_initialized = False
    auth.init_auth_system()
    legacy = sql("SELECT id,allowed_menus FROM dashboard_auth WHERE username='legacy-empty'")[0]
    assert legacy['allowed_menus'] == '*'
    sql("INSERT INTO dashboard_auth (username,role,allowed_menus,password_salt,password_hash) VALUES ('new-empty','Operator',NULL,'',%s)", (auth.hash_password('secret'),))
    new = sql("SELECT id,password_hash FROM dashboard_auth WHERE username='new-empty'")[0]
    token = auth.create_session(new['id'], new['password_hash'])
    assert auth.get_session_user(token)['allowed_menus'] == []
    assert menus.get_sidebar_menus(user_id=new['id']) == []
    assert next(u for u in users.get_dashboard_users_list() if u['id'] == new['id'])['allowed_menus'] == []
    client = TestClient(main.app)
    assert client.get('/api/stats', cookies={'session_token':token}).status_code == 403
    denied = client.get('/access-denied', cookies={'session_token':token})
    assert denied.status_code == 403 and 'href="/logout"' in denied.text
    auth._auth_initialized = False
    auth.init_auth_system()
    assert sql('SELECT allowed_menus FROM dashboard_auth WHERE id=%s', (new['id'],))[0]['allowed_menus'] is None
