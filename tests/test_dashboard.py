# tests/test_dashboard.py
import json
import sqlite3
import app as app_module
from conftest import register_user, login_user
from unittest.mock import patch

FAKE_METRICS = {
    'month': 2, 'year': 2026, 'patients': 125,
    'discharge_los_me': 3.47, 'discharge_los_peers': 3.8, 'discharge_los_pctile': 13.0,
    'admit_los_me': 5.36, 'admit_los_peers': 5.30, 'admit_los_pctile': 58.0,
    'admission_rate_me': 11.2, 'admission_rate_peers': 17.6, 'admission_rate_pctile': 15.0,
    'bed_request_me': 143.0, 'bed_request_peers': 171.0, 'bed_request_pctile': 28.0,
    'returns72_me': 4.0, 'returns72_peers': 4.4, 'returns72_pctile': 50.0,
    'readmits72_me': 1.6, 'readmits72_peers': 1.2, 'readmits72_pctile': 75.0,
    'rad_orders_me': 36.0, 'rad_orders_peers': 33.0, 'rad_orders_pctile': 50.0,
    'lab_orders_me': 47.0, 'lab_orders_peers': 53.0, 'lab_orders_pctile': 21.0,
    'pts_per_hour_me': 2.22, 'pts_per_hour_peers': 2.09, 'pts_per_hour_pctile': 45.0,
    'discharge_rate_me': 87.0, 'discharge_rate_peers': 79.0, 'discharge_rate_pctile': 87.5,
    'icu_rate_me': 0.0, 'icu_rate_peers': 0.03, 'icu_rate_pctile': 0.0,
    'rad_admit_me': 64.0, 'rad_admit_peers': 47.0,
    'rad_disc_me': 33.0, 'rad_disc_peers': 30.0,
    'esi1': 0.8, 'esi2': 20.0, 'esi3': 49.6, 'esi4': 23.2, 'esi5': 6.4,
    'billing_level3': 2, 'billing_level4': 22, 'billing_level5': 8,
}

def upload_month(client, metrics):
    import io
    with patch('app.parse_metrics', return_value=metrics):
        client.post('/upload', data={
            'pdf': (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf', 'application/pdf')
        }, content_type='multipart/form-data')

def test_dashboard_empty_state(client):
    register_user(client)
    login_user(client)
    rv = client.get('/dashboard')
    assert rv.status_code == 200
    assert b'upload' in rv.data.lower()

def test_dashboard_shows_data_after_upload(client):
    register_user(client)
    login_user(client)
    upload_month(client, FAKE_METRICS)
    rv = client.get('/dashboard')
    assert rv.status_code == 200
    assert b'3.47' in rv.data or b'125' in rv.data

def test_dashboard_month_filter(client):
    register_user(client)
    login_user(client)
    upload_month(client, FAKE_METRICS)
    m2 = {**FAKE_METRICS, 'month': 1, 'year': 2026, 'patients': 204}
    upload_month(client, m2)
    rv = client.get('/dashboard?month=1&year=2026')
    assert rv.status_code == 200

def test_dashboard_data_isolation(client):
    # user2 cannot see user1's data
    register_user(client, 'user1', 'password123')
    login_user(client, 'user1', 'password123')
    upload_month(client, FAKE_METRICS)
    client.post('/logout')
    register_user(client, 'user2', 'password456')
    login_user(client, 'user2', 'password456')
    rv = client.get('/dashboard')
    assert rv.status_code == 200
    # user2 sees empty state
    assert b'upload' in rv.data.lower()
