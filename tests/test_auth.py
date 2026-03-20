# tests/test_auth.py
import sqlite3
import app as app_module

def test_db_tables_exist(app):
    db = sqlite3.connect(app_module.DATABASE)
    tables = {r[0] for r in db.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()}
    assert 'users' in tables
    assert 'monthly_metrics' in tables
    assert 'insights_cache' in tables
    db.close()
