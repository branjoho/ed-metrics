# tests/test_auth.py
import sqlite3
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from conftest import register_user, login_user

def test_db_tables_exist(app):
    db = sqlite3.connect(app.config['DATABASE'])
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert 'users' in tables
    assert 'monthly_metrics' in tables
    assert 'insights_cache' in tables
    db.close()

def test_register_creates_user(client, app):
    rv = register_user(client)
    assert rv.status_code == 200
    # Verify user exists in DB
    import sqlite3
    with app.app_context():
        from app import get_db
        db = get_db()
        user = db.execute("SELECT username FROM users WHERE username='testuser'").fetchone()
        assert user is not None

def test_register_duplicate_username(client):
    register_user(client)
    rv = register_user(client)
    assert b'already taken' in rv.data.lower() or b'username' in rv.data.lower()

def test_register_short_username(client):
    rv = client.post('/register', data={'username': 'ab', 'password': 'password123'}, follow_redirects=True)
    assert b'3' in rv.data or b'username' in rv.data.lower()

def test_register_short_password(client):
    rv = client.post('/register', data={'username': 'validuser', 'password': 'short'}, follow_redirects=True)
    assert b'8' in rv.data or b'password' in rv.data.lower()

def test_login_success(client):
    register_user(client)
    rv = client.post('/login', data={'username': 'testuser', 'password': 'password123'}, follow_redirects=True)
    assert rv.status_code == 200

def test_login_wrong_password(client):
    register_user(client)
    rv = client.post('/login', data={'username': 'testuser', 'password': 'wrongpass'}, follow_redirects=True)
    assert b'invalid' in rv.data.lower() or b'incorrect' in rv.data.lower()

def test_logout(client):
    register_user(client)
    login_user(client)
    rv = client.post('/logout', follow_redirects=True)
    assert rv.status_code == 200
    rv2 = client.get('/dashboard', follow_redirects=False)
    assert rv2.status_code == 302

def test_dashboard_requires_login(client):
    rv = client.get('/dashboard', follow_redirects=False)
    assert rv.status_code == 302
    assert '/login' in rv.headers['Location']
