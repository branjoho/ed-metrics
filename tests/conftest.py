import pytest
from unittest.mock import patch
from datetime import datetime, timezone
from app import app as flask_app


# ---------------------------------------------------------------------------
# In-memory fake database
# ---------------------------------------------------------------------------

class FakeDB:
    def __init__(self):
        self.reset()

    def reset(self):
        self.users = {}       # {username: {id, username, password_hash, created_at}}
        self.metrics = []     # [{user_id, month, year, ...fields}]
        self.notes = []       # [{user_id, month, year, chart_key, note_text, ...}]
        self.insights = []    # [{user_id, month, year, chart_key, insight_text, generated_at}]
        self._next_id = 1


fake_db = FakeDB()


def _fake_get_user(username):
    return fake_db.users.get(username)


def _fake_get_user_by_id(user_id):
    for u in fake_db.users.values():
        if u['id'] == user_id:
            return u
    return None


def _fake_create_user(username, password_hash):
    user = {
        'id': fake_db._next_id,
        'username': username,
        'password_hash': password_hash,
        'created_at': datetime.now(timezone.utc).isoformat(),
    }
    fake_db.users[username] = user
    fake_db._next_id += 1
    return user


def _fake_get_metrics(user_id):
    return sorted(
        [m for m in fake_db.metrics if m['user_id'] == user_id],
        key=lambda r: (r['year'], r['month']),
    )


def _fake_upsert_metrics(user_id, metrics):
    import json
    m = dict(metrics)
    if isinstance(m.get('shift_data'), list):
        m['shift_data'] = json.dumps(m['shift_data'])
    fake_db.metrics[:] = [
        r for r in fake_db.metrics
        if not (r['user_id'] == user_id and r['month'] == m['month'] and r['year'] == m['year'])
    ]
    fake_db.metrics.append({'user_id': user_id, **m})
    fake_db.insights[:] = [r for r in fake_db.insights if r['user_id'] != user_id]


def _fake_delete_month(user_id, month, year):
    exists = any(
        r['user_id'] == user_id and r['month'] == month and r['year'] == year
        for r in fake_db.metrics
    )
    if not exists:
        return False
    fake_db.metrics[:] = [
        r for r in fake_db.metrics
        if not (r['user_id'] == user_id and r['month'] == month and r['year'] == year)
    ]
    fake_db.insights[:] = [
        r for r in fake_db.insights
        if not (r['user_id'] == user_id and r['month'] == month and r['year'] == year)
    ]
    return True


def _fake_get_all_notes(user_id):
    notes = {}
    for r in fake_db.notes:
        if r['user_id'] == user_id:
            key = f"{r['chart_key']}_{r['month']}_{r['year']}"
            notes[key] = r
    return notes


def _fake_upsert_note(user_id, month, year, chart_key, text):
    now = datetime.now(timezone.utc).isoformat()
    for r in fake_db.notes:
        if (r['user_id'] == user_id and r['month'] == month
                and r['year'] == year and r['chart_key'] == chart_key):
            r['note_text'] = text
            r['updated_at'] = now
            return
    fake_db.notes.append({
        'user_id': user_id, 'month': month, 'year': year,
        'chart_key': chart_key, 'note_text': text,
        'created_at': now, 'updated_at': now,
    })


def _fake_delete_note(user_id, month, year, chart_key):
    fake_db.notes[:] = [
        r for r in fake_db.notes
        if not (r['user_id'] == user_id and r['month'] == month
                and r['year'] == year and r['chart_key'] == chart_key)
    ]


def _fake_get_cached_insight(user_id, month, year, chart_key):
    import json
    from datetime import timedelta
    for r in fake_db.insights:
        if (r['user_id'] == user_id and r['month'] == month
                and r['year'] == year and r['chart_key'] == chart_key):
            generated_at = datetime.fromisoformat(r['generated_at'].replace('Z', '+00:00'))
            if datetime.now(timezone.utc) - generated_at < timedelta(days=90):
                return json.loads(r['insight_text'])
    return None


def _fake_save_insight_cache(user_id, month, year, chart_key, insights):
    import json
    fake_db.insights[:] = [
        r for r in fake_db.insights
        if not (r['user_id'] == user_id and r['month'] == month
                and r['year'] == year and r['chart_key'] == chart_key)
    ]
    fake_db.insights.append({
        'user_id': user_id, 'month': month, 'year': year, 'chart_key': chart_key,
        'insight_text': json.dumps(insights),
        'generated_at': datetime.now(timezone.utc).isoformat(),
    })


def _fake_get_all_insights(user_id):
    return [r for r in fake_db.insights if r['user_id'] == user_id]


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(autouse=True)
def reset_fake_db():
    fake_db.reset()
    yield


@pytest.fixture
def app():
    flask_app.config.update({'TESTING': True, 'WTF_CSRF_ENABLED': False})
    with patch.multiple(
        'flask_db',
        get_user=_fake_get_user,
        get_user_by_id=_fake_get_user_by_id,
        create_user=_fake_create_user,
        get_metrics=_fake_get_metrics,
        upsert_metrics=_fake_upsert_metrics,
        delete_month=_fake_delete_month,
        get_all_notes=_fake_get_all_notes,
        upsert_note=_fake_upsert_note,
        delete_note=_fake_delete_note,
        get_cached_insight=_fake_get_cached_insight,
        save_insight_cache=_fake_save_insight_cache,
        get_all_insights=_fake_get_all_insights,
    ):
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
