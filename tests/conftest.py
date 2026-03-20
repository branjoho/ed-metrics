import os
import pytest
from app import app as flask_app, init_db
import app as app_module

@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / 'test.db')
    flask_app.config.update({
        'TESTING': True,
        'DATABASE': db_path,
        'WTF_CSRF_ENABLED': False,
    })
    app_module.DATABASE = db_path
    init_db()
    yield flask_app

@pytest.fixture
def client(app):
    return app.test_client()

def register_user(client, username='testuser', password='password123'):
    return client.post('/register', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)

def login_user(client, username='testuser', password='password123'):
    return client.post('/login', data={
        'username': username,
        'password': password,
    }, follow_redirects=True)
