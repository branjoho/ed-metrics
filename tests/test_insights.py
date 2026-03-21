# tests/test_insights.py
import json
import sqlite3
import app as app_module
from conftest import register_user, login_user
from unittest.mock import patch, MagicMock
import io

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

MOCK_INSIGHT_RESPONSE = [
    {"severity": "good", "text": "You are faster than peers.", "tags": ["pos"]}
]

def upload_month(client, metrics=FAKE_METRICS):
    with patch('app.parse_metrics', return_value=metrics):
        client.post('/upload', data={
            'pdf': (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf', 'application/pdf')
        }, content_type='multipart/form-data')

def mock_anthropic_response(text):
    mock = MagicMock()
    mock.content = [MagicMock(text=json.dumps(text))]
    return mock

def test_insights_cache_miss_calls_api(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    with patch('app.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_anthropic_response(MOCK_INSIGHT_RESPONSE)
        rv = client.get('/api/insights/dischargeLOS/2/2026')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert isinstance(data, list)
    assert data[0]['severity'] == 'good'
    assert mock_client.messages.create.called

def test_insights_cache_hit_skips_api(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    with patch('app.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_anthropic_response(MOCK_INSIGHT_RESPONSE)
        client.get('/api/insights/dischargeLOS/2/2026')  # populate cache
        mock_client.messages.create.reset_mock()
        rv = client.get('/api/insights/dischargeLOS/2/2026')  # should hit cache
    assert rv.status_code == 200
    assert not mock_client.messages.create.called

def test_insights_api_error_returns_error_json(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    with patch('app.anthropic_client') as mock_client:
        mock_client.messages.create.side_effect = Exception("API error")
        rv = client.get('/api/insights/dischargeLOS/2/2026')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert 'error' in data

def test_insights_no_api_key(client, monkeypatch):
    monkeypatch.delenv('ANTHROPIC_API_KEY', raising=False)
    register_user(client)
    login_user(client)
    upload_month(client)
    with patch('app.anthropic_client', None):
        rv = client.get('/api/insights/dischargeLOS/2/2026')
    assert rv.status_code == 200
    data = json.loads(rv.data)
    assert 'error' in data

def test_insights_cache_cleared_on_upload(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    with patch('app.anthropic_client') as mock_client:
        mock_client.messages.create.return_value = mock_anthropic_response(MOCK_INSIGHT_RESPONSE)
        client.get('/api/insights/dischargeLOS/2/2026')
    # Upload again (clears cache)
    upload_month(client)
    db = sqlite3.connect(app_module.app.config['DATABASE'])
    count = db.execute("SELECT COUNT(*) FROM insights_cache").fetchone()[0]
    assert count == 0
    db.close()
