# tests/test_delete.py
import json
import sqlite3
import io
import app as app_module
from conftest import register_user, login_user
from unittest.mock import patch

FAKE_METRICS = {
    'month': 2, 'year': 2026, 'patients': 125,
    'discharge_los_me': 3.47, 'discharge_los_peers': 3.8, 'discharge_los_pctile': 13.0,
    'admit_los_me': None, 'admit_los_peers': None, 'admit_los_pctile': None,
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
    'billing_level3': None, 'billing_level4': None, 'billing_level5': None,
}

def upload_month(client, metrics=FAKE_METRICS):
    with patch('app.parse_metrics', return_value=metrics):
        client.post('/upload', data={
            'pdfs': (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf', 'application/pdf')
        }, content_type='multipart/form-data')

def test_delete_month_removes_row(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    rv = client.delete('/api/months/2/2026')
    assert rv.status_code == 200
    db = sqlite3.connect(app_module.app.config['DATABASE'])
    row = db.execute('SELECT * FROM monthly_metrics WHERE month=2 AND year=2026').fetchone()
    assert row is None
    db.close()

def test_delete_cascades_insights_cache(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    # Manually insert a cache row
    db = sqlite3.connect(app_module.app.config['DATABASE'])
    user = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()
    db.execute("INSERT INTO insights_cache (user_id, month, year, chart_key, insight_text, generated_at) VALUES (?,2,2026,'dischargeLOS','[]','2026-01-01')", (user[0],))
    db.commit()
    db.close()
    client.delete('/api/months/2/2026')
    db = sqlite3.connect(app_module.app.config['DATABASE'])
    count = db.execute("SELECT COUNT(*) FROM insights_cache WHERE month=2 AND year=2026").fetchone()[0]
    assert count == 0
    db.close()

def test_delete_does_not_affect_other_user(client):
    # user1 uploads
    register_user(client, 'user1', 'password123')
    login_user(client, 'user1', 'password123')
    upload_month(client)
    client.post('/logout')
    # user2 uploads same month
    register_user(client, 'user2', 'password456')
    login_user(client, 'user2', 'password456')
    upload_month(client)
    # user2 deletes their own
    client.delete('/api/months/2/2026')
    client.post('/logout')
    # user1's data should still exist
    login_user(client, 'user1', 'password123')
    db = sqlite3.connect(app_module.app.config['DATABASE'])
    user1 = db.execute("SELECT id FROM users WHERE username='user1'").fetchone()
    row = db.execute('SELECT * FROM monthly_metrics WHERE user_id=? AND month=2 AND year=2026', (user1[0],)).fetchone()
    assert row is not None
    db.close()

def test_delete_nonexistent_month_returns_404(client):
    register_user(client)
    login_user(client)
    rv = client.delete('/api/months/12/2020')
    assert rv.status_code == 404
