# tests/test_auth.py
import sqlite3

def test_db_tables_exist(app):
    db = sqlite3.connect(app.config['DATABASE'])
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert 'users' in tables
    assert 'monthly_metrics' in tables
    assert 'insights_cache' in tables
    db.close()
