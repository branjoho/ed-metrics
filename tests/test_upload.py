import io
import pytest
from unittest.mock import patch
import sqlite3
from parse_pdf import parse_metrics, ParseError

REAL_PDF = "/Users/branjoho/Documents/Attending metrics/2_2026 - ED Provider Metrics.pdf"

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
    'billing_level3': 16, 'billing_level4': 59, 'billing_level5': 25,
}

def fake_pdf():
    return (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf', 'application/pdf')

def test_upload_get_requires_login(client):
    rv = client.get('/upload', follow_redirects=False)
    assert rv.status_code == 302

def test_upload_get_renders_form(client):
    from conftest import register_user, login_user
    register_user(client)
    login_user(client)
    rv = client.get('/upload')
    assert rv.status_code == 200
    assert b'upload' in rv.data.lower() or b'pdf' in rv.data.lower()

def test_upload_stores_metrics(client, app):
    from conftest import register_user, login_user
    register_user(client)
    login_user(client)
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        rv = client.post('/upload', data={'pdf': fake_pdf()},
                         content_type='multipart/form-data', follow_redirects=True)
    assert rv.status_code == 200
    with app.app_context():
        from app import get_db
        db = get_db()
        row = db.execute('SELECT * FROM monthly_metrics WHERE month=2 AND year=2026').fetchone()
        assert row is not None
        assert row['patients'] == 125

def test_upload_upsert_overwrites(client, app):
    from conftest import register_user, login_user
    register_user(client)
    login_user(client)
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf()}, content_type='multipart/form-data')
    updated = {**FAKE_METRICS, 'patients': 999}
    with patch('app.parse_metrics', return_value=updated):
        client.post('/upload', data={'pdf': fake_pdf()}, content_type='multipart/form-data')
    with app.app_context():
        from app import get_db
        db = get_db()
        rows = db.execute('SELECT patients FROM monthly_metrics WHERE month=2 AND year=2026').fetchall()
        assert len(rows) == 1
        assert rows[0]['patients'] == 999

def test_upload_bad_mime_rejected(client):
    from conftest import register_user, login_user
    register_user(client)
    login_user(client)
    rv = client.post('/upload', data={
        'pdf': (io.BytesIO(b'not a pdf'), 'test.txt', 'text/plain')
    }, content_type='multipart/form-data', follow_redirects=True)
    assert b'pdf' in rv.data.lower()

def test_upload_clears_insights_cache(client, app):
    from conftest import register_user, login_user
    register_user(client)
    login_user(client)
    # Seed a cache row
    with app.app_context():
        from app import get_db
        db = get_db()
        user = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()
        db.execute(
            "INSERT INTO insights_cache (user_id, month, year, chart_key, insight_text, generated_at) "
            "VALUES (?,2,2026,'dischargeLOS','[]','2026-01-01')", (user['id'],))
        db.commit()
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf()}, content_type='multipart/form-data')
    with app.app_context():
        from app import get_db
        db = get_db()
        count = db.execute("SELECT COUNT(*) FROM insights_cache").fetchone()[0]
        assert count == 0

def test_upload_isolation(client, app):
    from conftest import register_user, login_user
    register_user(client, 'user1', 'password123')
    login_user(client, 'user1', 'password123')
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf()}, content_type='multipart/form-data')
    client.post('/logout')
    register_user(client, 'user2', 'password456')
    login_user(client, 'user2', 'password456')
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf()}, content_type='multipart/form-data')
    with app.app_context():
        from app import get_db
        db = get_db()
        rows = db.execute('SELECT user_id FROM monthly_metrics WHERE month=2 AND year=2026').fetchall()
        assert len(rows) == 2
        assert rows[0]['user_id'] != rows[1]['user_id']

def test_parse_returns_dict():
    result = parse_metrics(REAL_PDF)
    assert isinstance(result, dict)

def test_parse_required_keys():
    result = parse_metrics(REAL_PDF)
    required = ['month', 'year', 'patients', 'discharge_los_me', 'discharge_los_peers']
    for key in required:
        assert key in result, f"Missing key: {key}"

def test_parse_numeric_values():
    result = parse_metrics(REAL_PDF)
    assert isinstance(result['patients'], (int, type(None)))
    assert isinstance(result['discharge_los_me'], (float, type(None)))

def test_parse_wrong_file_raises():
    import tempfile, os
    with tempfile.NamedTemporaryFile(suffix='.pdf', delete=False) as f:
        f.write(b'%PDF-1.4 not a real metrics file')
        path = f.name
    try:
        with pytest.raises(ParseError):
            parse_metrics(path)
    finally:
        os.unlink(path)

def test_parse_nonexistent_file_raises():
    with pytest.raises(FileNotFoundError):
        parse_metrics('/nonexistent/path/file.pdf')
