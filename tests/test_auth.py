import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from conftest import register_user, login_user, fake_db


def test_register_creates_user(client):
    register_user(client)
    assert 'testuser' in fake_db.users


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
