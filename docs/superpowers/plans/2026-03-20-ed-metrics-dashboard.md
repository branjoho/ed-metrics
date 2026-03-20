# ED Provider Metrics Dashboard Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Flask web app where ED providers upload monthly metrics PDFs, get a polished Chart.js dashboard with LLM insights, and see their history over time.

**Architecture:** Single Flask app with SQLite. PDF uploads are parsed via pdfplumber and stored per-user. The dashboard adapts an existing polished HTML file to Jinja2 with server-rendered data. LLM insights are generated on-demand via the Claude API and cached in the DB.

**Tech Stack:** Python 3.11+, Flask, flask-login, flask-bcrypt, pdfplumber, anthropic SDK, SQLite, Chart.js 4.4, Jinja2

---

## File Map

| File | Responsibility |
|------|----------------|
| `app.py` | Flask app init, DB schema + helpers, all routes |
| `parse_pdf.py` | `parse_metrics(path) -> dict`, `ParseError` |
| `requirements.txt` | All Python dependencies |
| `.env.example` | API key placeholder |
| `.gitignore` | Excludes DB, .env, PDFs, __pycache__ |
| `templates/base.html` | Nav, flash messages, session state |
| `templates/login.html` | Login form |
| `templates/register.html` | Registration form |
| `templates/dashboard.html` | Full Chart.js dashboard (Jinja2 adaptation) |
| `templates/upload.html` | PDF upload form |
| `static/style.css` | Minimal CSS overrides |
| `tests/conftest.py` | pytest fixtures: app, client, temp DB, auth helpers |
| `tests/test_auth.py` | Register, login, logout, validation, isolation |
| `tests/test_upload.py` | Upload routes, upsert, parse errors, MIME check |
| `tests/test_dashboard.py` | Dashboard route, data shape, empty state, month filter |
| `tests/test_insights.py` | Cache hit/miss, API error, cache invalidation |
| `tests/test_delete.py` | DELETE month cascade |

---

## Task 1: Project Scaffold

**Files:**
- Create: `requirements.txt`
- Create: `.gitignore`
- Create: `.env.example`
- Create: `app.py` (skeleton)
- Create: `tests/conftest.py`

- [ ] **Step 1: Create `requirements.txt`**

```
flask>=3.0
flask-login>=0.6
flask-bcrypt>=1.0
pdfplumber>=0.11
anthropic>=0.25
pytest>=8.0
pytest-flask>=1.3
python-dotenv>=1.0
```

- [ ] **Step 2: Create `.gitignore`**

```
metrics.db
.env
__pycache__/
*.pyc
*.pdf
tmp/
.pytest_cache/
```

- [ ] **Step 3: Create `.env.example`**

```
ANTHROPIC_API_KEY=your_key_here
SECRET_KEY=change_this_to_a_random_string
```

- [ ] **Step 4: Create `app.py` with Flask init, DB schema, and helpers**

```python
import os
import sqlite3
from datetime import datetime, timezone
from flask import Flask, g
from flask_login import LoginManager
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB
app.config['DATABASE'] = os.path.join(app.instance_path, 'metrics.db')

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

os.makedirs(app.instance_path, exist_ok=True)

DATABASE = os.environ.get('DATABASE', app.config['DATABASE'])

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monthly_metrics (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    patients INTEGER,
    discharge_los_me REAL, discharge_los_peers REAL, discharge_los_pctile REAL,
    admit_los_me REAL, admit_los_peers REAL, admit_los_pctile REAL,
    admission_rate_me REAL, admission_rate_peers REAL, admission_rate_pctile REAL,
    bed_request_me REAL, bed_request_peers REAL, bed_request_pctile REAL,
    returns72_me REAL, returns72_peers REAL, returns72_pctile REAL,
    readmits72_me REAL, readmits72_peers REAL, readmits72_pctile REAL,
    rad_orders_me REAL, rad_orders_peers REAL, rad_orders_pctile REAL,
    lab_orders_me REAL, lab_orders_peers REAL, lab_orders_pctile REAL,
    pts_per_hour_me REAL, pts_per_hour_peers REAL, pts_per_hour_pctile REAL,
    discharge_rate_me REAL, discharge_rate_peers REAL, discharge_rate_pctile REAL,
    icu_rate_me REAL, icu_rate_peers REAL, icu_rate_pctile REAL,
    rad_admit_me REAL, rad_admit_peers REAL,
    rad_disc_me REAL, rad_disc_peers REAL,
    esi1 REAL, esi2 REAL, esi3 REAL, esi4 REAL, esi5 REAL,
    billing_level3 INTEGER, billing_level4 INTEGER, billing_level5 INTEGER,
    UNIQUE(user_id, month, year)
);

CREATE TABLE IF NOT EXISTS insights_cache (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id),
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    chart_key TEXT NOT NULL,
    insight_text TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE(user_id, month, year, chart_key)
);
"""

def get_db():
    if 'db' not in g:
        g.db = sqlite3.connect(DATABASE, detect_types=sqlite3.PARSE_DECLTYPES)
        g.db.row_factory = sqlite3.Row
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    db = sqlite3.connect(DATABASE)
    db.executescript(SCHEMA)
    db.commit()
    db.close()

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
```

- [ ] **Step 5: Create `tests/conftest.py`**

```python
import os
import tempfile
import pytest
from app import app as flask_app, init_db, DATABASE

@pytest.fixture
def app(tmp_path):
    db_path = str(tmp_path / 'test.db')
    flask_app.config.update({
        'TESTING': True,
        'DATABASE': db_path,
        'WTF_CSRF_ENABLED': False,
    })
    import app as app_module
    app_module.DATABASE = db_path
    init_db()
    yield flask_app
    # cleanup handled by tmp_path

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
```

- [ ] **Step 6: Write failing tests for DB initialization**

```python
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
```

- [ ] **Step 7: Run test to verify it fails**

```bash
cd /Users/branjoho/Documents/Claude/claude_test/ed-metrics
pip install -r requirements.txt
pytest tests/test_auth.py::test_db_tables_exist -v
```
Expected: FAIL (app.py missing routes/models, import errors)

- [ ] **Step 8: Run test after scaffold is in place**

```bash
pytest tests/test_auth.py::test_db_tables_exist -v
```
Expected: PASS

- [ ] **Step 9: Commit**

```bash
git add app.py requirements.txt .gitignore .env.example tests/conftest.py tests/test_auth.py
git commit -m "feat: project scaffold with DB schema and test fixtures"
```

---

## Task 2: Auth Routes + Templates

**Files:**
- Modify: `app.py` (add User class, register/login/logout routes)
- Create: `templates/base.html`
- Create: `templates/login.html`
- Create: `templates/register.html`
- Modify: `tests/test_auth.py`

- [ ] **Step 1: Write failing auth tests**

```python
# tests/test_auth.py (add after existing test)
from conftest import register_user, login_user

def test_register_creates_user(client):
    rv = register_user(client)
    assert rv.status_code == 200
    # Should redirect to dashboard or login after register

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
    # After logout, /dashboard should redirect to login
    rv2 = client.get('/dashboard', follow_redirects=False)
    assert rv2.status_code == 302

def test_dashboard_requires_login(client):
    rv = client.get('/dashboard', follow_redirects=False)
    assert rv.status_code == 302
    assert '/login' in rv.headers['Location']
```

- [ ] **Step 2: Run to verify tests fail**

```bash
pytest tests/test_auth.py -v
```
Expected: FAIL (no routes defined yet)

- [ ] **Step 3: Add User class and auth routes to `app.py`**

Add after the DB helpers:

```python
from flask import render_template, redirect, url_for, flash, request, session
from flask_login import UserMixin, login_user, logout_user, login_required, current_user
import re

class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    db = get_db()
    row = db.execute('SELECT id, username FROM users WHERE id = ?', (user_id,)).fetchone()
    if row:
        return User(row['id'], row['username'])
    return None

@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        error = None
        if not re.match(r'^[a-zA-Z0-9_]{3,32}$', username):
            error = 'Username must be 3–32 characters (letters, numbers, underscores only).'
        elif len(password) < 8:
            error = 'Password must be at least 8 characters.'
        if error:
            flash(error, 'error')
            return render_template('register.html', username=username)
        pw_hash = bcrypt.generate_password_hash(password).decode('utf-8')
        try:
            db = get_db()
            db.execute(
                'INSERT INTO users (username, password_hash, created_at) VALUES (?, ?, ?)',
                (username, pw_hash, datetime.now(timezone.utc).isoformat())
            )
            db.commit()
        except sqlite3.IntegrityError:
            flash('Username already taken.', 'error')
            return render_template('register.html', username=username)
        flash('Account created. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        db = get_db()
        row = db.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
        if row and bcrypt.check_password_hash(row['password_hash'], password):
            user = User(row['id'], row['username'])
            login_user(user)
            return redirect(url_for('dashboard'))
        flash('Invalid username or password.', 'error')
    return render_template('login.html')

@app.route('/logout', methods=['POST'])
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', metrics_json={}, months=[])
```

- [ ] **Step 4: Create `templates/base.html`**

```html
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>ED Provider Dashboard</title>
<link rel="stylesheet" href="{{ url_for('static', filename='style.css') }}">
</head>
<body>
<nav>
  <span class="brand">ED Provider Dashboard</span>
  {% if current_user.is_authenticated %}
    <span class="nav-user">{{ current_user.username }}</span>
    <a href="{{ url_for('upload_page') }}">Upload PDF</a>
    <form method="post" action="{{ url_for('logout') }}" style="display:inline">
      <button type="submit" class="nav-link-btn">Logout</button>
    </form>
  {% endif %}
</nav>
{% with messages = get_flashed_messages(with_categories=true) %}
  {% if messages %}
    <div class="flash-container">
      {% for category, message in messages %}
        <div class="flash flash-{{ category }}">{{ message }}</div>
      {% endfor %}
    </div>
  {% endif %}
{% endwith %}
{% block content %}{% endblock %}
</body>
</html>
```

- [ ] **Step 5: Create `templates/login.html`**

```html
{% extends 'base.html' %}
{% block content %}
<main class="auth-page">
  <h1>Sign In</h1>
  <form method="post">
    <label>Username<input type="text" name="username" required autofocus></label>
    <label>Password<input type="password" name="password" required></label>
    <button type="submit">Sign In</button>
  </form>
  <p><a href="{{ url_for('register') }}">Create an account</a></p>
</main>
{% endblock %}
```

- [ ] **Step 6: Create `templates/register.html`**

```html
{% extends 'base.html' %}
{% block content %}
<main class="auth-page">
  <h1>Create Account</h1>
  <form method="post">
    <label>Username (3–32 chars, letters/numbers/underscores)
      <input type="text" name="username" value="{{ username or '' }}" required autofocus>
    </label>
    <label>Password (min 8 characters)
      <input type="password" name="password" required>
    </label>
    <button type="submit">Create Account</button>
  </form>
  <p><a href="{{ url_for('login') }}">Already have an account?</a></p>
</main>
{% endblock %}
```

- [ ] **Step 7: Create `static/style.css`** (auth page layout only; dashboard has its own inline styles)

```css
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Segoe UI', system-ui, sans-serif; background: #f8fafc; color: #1e293b; }
nav {
  position: sticky; top: 0; z-index: 100;
  background: rgba(255,255,255,0.97); border-bottom: 1px solid #e2e8f0;
  display: flex; align-items: center; padding: 0 24px; height: 56px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
}
.brand { font-weight: 800; font-size: 16px; color: #2563eb; margin-right: auto; }
nav a, .nav-link-btn {
  color: #64748b; text-decoration: none; font-size: 14px; font-weight: 500;
  padding: 0 14px; height: 56px; display: flex; align-items: center;
  border: none; background: none; cursor: pointer; font-family: inherit;
}
nav a:hover, .nav-link-btn:hover { color: #1e293b; }
.nav-user { font-size: 14px; color: #64748b; padding: 0 14px; }
.flash-container { padding: 12px 24px; }
.flash { padding: 10px 16px; border-radius: 8px; margin-bottom: 8px; font-size: 14px; }
.flash-error { background: #fee2e2; color: #dc2626; }
.flash-success { background: #dcfce7; color: #16a34a; }
.flash-info { background: #dbeafe; color: #2563eb; }
.auth-page { max-width: 400px; margin: 80px auto; padding: 40px; background: #fff;
  border: 1px solid #e2e8f0; border-radius: 12px; }
.auth-page h1 { font-size: 22px; font-weight: 700; margin-bottom: 24px; }
.auth-page label { display: block; font-size: 14px; font-weight: 600; margin-bottom: 16px; }
.auth-page input { display: block; width: 100%; margin-top: 4px; padding: 9px 12px;
  border: 1px solid #e2e8f0; border-radius: 7px; font-size: 14px; font-family: inherit; }
.auth-page button[type=submit] { width: 100%; padding: 10px; background: #2563eb; color: #fff;
  border: none; border-radius: 8px; font-size: 14px; font-weight: 700;
  font-family: inherit; cursor: pointer; margin-top: 8px; }
.auth-page p { margin-top: 16px; font-size: 13px; text-align: center; color: #64748b; }
```

- [ ] **Step 8: Run auth tests**

```bash
pytest tests/test_auth.py -v
```
Expected: All 9 tests PASS

- [ ] **Step 9: Commit**

```bash
git add app.py templates/ static/style.css tests/test_auth.py
git commit -m "feat: auth routes (register, login, logout) with validation"
```

---

## Task 3: PDF Parser

**Files:**
- Create: `parse_pdf.py`
- Create: `tests/test_upload.py` (parser tests only for this task)

> **Important:** The parser must be written by examining the actual PDFs at `/Users/branjoho/Documents/Attending\ metrics/`. Step 1 is a mandatory exploration step — do not skip it.

- [ ] **Step 1: Run PDF exploration script to understand page layout**

```python
# Run this interactively or as a one-off script (do not commit):
import pdfplumber, os, glob

pdf_dir = "/Users/branjoho/Documents/Attending metrics/"
pdfs = sorted(glob.glob(os.path.join(pdf_dir, "*.pdf")))

for pdf_path in pdfs[:2]:  # examine first 2 PDFs
    print(f"\n=== {os.path.basename(pdf_path)} ===")
    with pdfplumber.open(pdf_path) as pdf:
        print(f"Total pages: {len(pdf.pages)}")
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ""
            if text.strip():
                print(f"\n--- Page {i+1} (first 600 chars) ---")
                print(text[:600])
```

Run it:
```bash
python3 -c "
import pdfplumber, os, glob
pdf_dir = '/Users/branjoho/Documents/Attending metrics/'
pdfs = sorted(glob.glob(os.path.join(pdf_dir, '*.pdf')))
for pdf_path in pdfs[:2]:
    print(f'\n=== {os.path.basename(pdf_path)} ===')
    with pdfplumber.open(pdf_path) as pdf:
        print(f'Total pages: {len(pdf.pages)}')
        for i, page in enumerate(pdf.pages):
            text = page.extract_text() or ''
            if text.strip():
                print(f'\n--- Page {i+1} ---')
                print(text[:800])
"
```

Study the output to find which pages contain each metric and what the text patterns look like (e.g., "Discharge LOS: 3.47 hrs (Peers: 3.8)"). Note the exact format for each field.

- [ ] **Step 2: Write failing parser tests**

```python
# tests/test_upload.py
import pytest
from parse_pdf import parse_metrics, ParseError

REAL_PDF = "/Users/branjoho/Documents/Attending metrics/2_2026 - ED Provider Metrics.pdf"

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
    with pytest.raises((ParseError, Exception)):
        parse_metrics('/nonexistent/path/file.pdf')
```

- [ ] **Step 3: Run to confirm tests fail**

```bash
pytest tests/test_upload.py::test_parse_returns_dict tests/test_upload.py::test_parse_wrong_file_raises -v
```
Expected: FAIL (parse_pdf.py doesn't exist yet)

- [ ] **Step 4: Implement `parse_pdf.py`**

Based on what you found in Step 1, implement the parser. The structure must follow this interface exactly:

```python
import re
import pdfplumber

class ParseError(Exception):
    pass

# Map of DB field names to (page_index, regex_pattern) discovered in Step 1
# Fill in FIELD_PATTERNS based on your PDF exploration:
FIELD_PATTERNS = {
    # Example (replace with actual patterns from your PDFs):
    # 'discharge_los_me': (page_num, r'Discharge LOS.*?(\d+\.\d+)'),
    # 'discharge_los_peers': (page_num, r'Discharge LOS.*?Peers?:?\s*(\d+\.\d+)'),
    # ...
}

def _extract_float(text, pattern):
    """Return first float match or None."""
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if m:
        try:
            return float(m.group(1).replace(',', ''))
        except ValueError:
            return None
    return None

def _extract_int(text, pattern):
    m = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
    if m:
        try:
            return int(m.group(1).replace(',', ''))
        except ValueError:
            return None
    return None

def parse_metrics(pdf_path: str) -> dict:
    """
    Parse an ED Provider Metrics PDF.
    Returns a dict of all metric fields (values may be None if not found).
    Raises ParseError if the file is not a recognized ED metrics PDF.
    """
    try:
        with pdfplumber.open(pdf_path) as pdf:
            pages = [p.extract_text() or '' for p in pdf.pages]
    except Exception as e:
        raise ParseError(f"Could not open PDF: {e}")

    # Validate it's the right kind of file
    full_text = ' '.join(pages)
    if 'ED Provider' not in full_text and 'Emergency Department' not in full_text:
        raise ParseError(
            "This doesn't look like an ED Provider Metrics PDF. Please upload the correct file."
        )

    # Extract month/year from filename or PDF content
    # e.g. "2_2026 - ED Provider Metrics.pdf" -> month=2, year=2026
    import re as _re
    month_match = _re.search(r'(\d{1,2})[_/](\d{4})', pdf_path)
    month = int(month_match.group(1)) if month_match else None
    year = int(month_match.group(2)) if month_match else None

    result = {'month': month, 'year': year}

    # Extract each field using patterns discovered in Step 1
    # Fill in based on actual PDF content:
    for field, (page_idx, pattern) in FIELD_PATTERNS.items():
        if page_idx < len(pages):
            if field.endswith('_pctile') or field in ('patients', 'billing_level3', 'billing_level4', 'billing_level5'):
                result[field] = _extract_int(pages[page_idx], pattern) or _extract_float(pages[page_idx], pattern)
            else:
                result[field] = _extract_float(pages[page_idx], pattern)
        else:
            result[field] = None

    # Set any missing fields to None explicitly
    ALL_FIELDS = [
        'patients',
        'discharge_los_me', 'discharge_los_peers', 'discharge_los_pctile',
        'admit_los_me', 'admit_los_peers', 'admit_los_pctile',
        'admission_rate_me', 'admission_rate_peers', 'admission_rate_pctile',
        'bed_request_me', 'bed_request_peers', 'bed_request_pctile',
        'returns72_me', 'returns72_peers', 'returns72_pctile',
        'readmits72_me', 'readmits72_peers', 'readmits72_pctile',
        'rad_orders_me', 'rad_orders_peers', 'rad_orders_pctile',
        'lab_orders_me', 'lab_orders_peers', 'lab_orders_pctile',
        'pts_per_hour_me', 'pts_per_hour_peers', 'pts_per_hour_pctile',
        'discharge_rate_me', 'discharge_rate_peers', 'discharge_rate_pctile',
        'icu_rate_me', 'icu_rate_peers', 'icu_rate_pctile',
        'rad_admit_me', 'rad_admit_peers', 'rad_disc_me', 'rad_disc_peers',
        'esi1', 'esi2', 'esi3', 'esi4', 'esi5',
        'billing_level3', 'billing_level4', 'billing_level5',
    ]
    for field in ALL_FIELDS:
        result.setdefault(field, None)

    return result
```

- [ ] **Step 5: Run parser tests**

```bash
pytest tests/test_upload.py::test_parse_returns_dict tests/test_upload.py::test_parse_required_keys tests/test_upload.py::test_parse_wrong_file_raises -v
```
Expected: PASS (adjust patterns in FIELD_PATTERNS until values are extracted correctly)

- [ ] **Step 6: Verify actual values look right**

```bash
python3 -c "
from parse_pdf import parse_metrics
r = parse_metrics('/Users/branjoho/Documents/Attending metrics/2_2026 - ED Provider Metrics.pdf')
for k, v in sorted(r.items()):
    print(f'{k}: {v}')
"
```
Compare output to known values from the existing dashboard HTML:
- `discharge_los_me` should be ~3.47
- `patients` should be ~125
- `admission_rate_me` should be ~11.2

- [ ] **Step 7: Commit**

```bash
git add parse_pdf.py tests/test_upload.py
git commit -m "feat: PDF parser for ED metrics reports"
```

---

## Task 4: Upload Route

**Files:**
- Modify: `app.py` (add upload routes, upsert helper)
- Create: `templates/upload.html`
- Modify: `tests/test_upload.py`

- [ ] **Step 1: Write failing upload route tests**

```python
# tests/test_upload.py (add after parser tests)
import io
from conftest import register_user, login_user
import sqlite3
import app as app_module
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

def fake_pdf_data():
    return (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf', 'application/pdf')

def test_upload_get_requires_login(client):
    rv = client.get('/upload', follow_redirects=False)
    assert rv.status_code == 302

def test_upload_get_renders_form(client):
    register_user(client)
    login_user(client)
    rv = client.get('/upload')
    assert rv.status_code == 200
    assert b'upload' in rv.data.lower()

def test_upload_stores_metrics(client):
    register_user(client)
    login_user(client)
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        rv = client.post('/upload', data={
            'pdf': fake_pdf_data()
        }, content_type='multipart/form-data', follow_redirects=True)
    assert rv.status_code == 200
    db = sqlite3.connect(app_module.DATABASE)
    row = db.execute('SELECT * FROM monthly_metrics WHERE month=2 AND year=2026').fetchone()
    assert row is not None
    db.close()

def test_upload_upsert_overwrites(client):
    register_user(client)
    login_user(client)
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf_data()},
                    content_type='multipart/form-data')
    updated = {**FAKE_METRICS, 'patients': 999}
    with patch('app.parse_metrics', return_value=updated):
        client.post('/upload', data={'pdf': fake_pdf_data()},
                    content_type='multipart/form-data')
    db = sqlite3.connect(app_module.DATABASE)
    rows = db.execute('SELECT patients FROM monthly_metrics WHERE month=2 AND year=2026').fetchall()
    assert len(rows) == 1  # upsert, not duplicate
    assert rows[0][0] == 999
    db.close()

def test_upload_bad_mime_rejected(client):
    register_user(client)
    login_user(client)
    rv = client.post('/upload', data={
        'pdf': (io.BytesIO(b'not a pdf'), 'test.txt', 'text/plain')
    }, content_type='multipart/form-data', follow_redirects=True)
    assert b'pdf' in rv.data.lower()

def test_upload_clears_insights_cache(client):
    register_user(client)
    login_user(client)
    # Manually insert a cache row
    db = sqlite3.connect(app_module.DATABASE)
    user = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()
    db.execute("INSERT INTO insights_cache (user_id, month, year, chart_key, insight_text, generated_at) VALUES (?,2,2026,'dischargeLOS','[]','2026-01-01')", (user[0],))
    db.commit()
    db.close()
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf_data()},
                    content_type='multipart/form-data')
    db = sqlite3.connect(app_module.DATABASE)
    count = db.execute("SELECT COUNT(*) FROM insights_cache").fetchone()[0]
    assert count == 0
    db.close()

def test_upload_isolation(client):
    # Two users upload same month — each should only see their own row
    register_user(client, 'user1', 'password123')
    login_user(client, 'user1', 'password123')
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf_data()}, content_type='multipart/form-data')
    client.post('/logout')
    register_user(client, 'user2', 'password456')
    login_user(client, 'user2', 'password456')
    with patch('app.parse_metrics', return_value=FAKE_METRICS):
        client.post('/upload', data={'pdf': fake_pdf_data()}, content_type='multipart/form-data')
    db = sqlite3.connect(app_module.DATABASE)
    rows = db.execute('SELECT user_id FROM monthly_metrics WHERE month=2 AND year=2026').fetchall()
    assert len(rows) == 2  # one per user
    assert rows[0][0] != rows[1][0]
    db.close()
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_upload.py -k "upload" -v
```
Expected: FAIL

- [ ] **Step 3: Add upload routes to `app.py`**

Add these imports at the top of app.py:
```python
import tempfile, os
from parse_pdf import parse_metrics, ParseError
```

Add these routes:

```python
ALLOWED_MIME = {'application/pdf'}

def _upsert_metrics(user_id, metrics):
    db = get_db()
    fields = [
        'patients',
        'discharge_los_me', 'discharge_los_peers', 'discharge_los_pctile',
        'admit_los_me', 'admit_los_peers', 'admit_los_pctile',
        'admission_rate_me', 'admission_rate_peers', 'admission_rate_pctile',
        'bed_request_me', 'bed_request_peers', 'bed_request_pctile',
        'returns72_me', 'returns72_peers', 'returns72_pctile',
        'readmits72_me', 'readmits72_peers', 'readmits72_pctile',
        'rad_orders_me', 'rad_orders_peers', 'rad_orders_pctile',
        'lab_orders_me', 'lab_orders_peers', 'lab_orders_pctile',
        'pts_per_hour_me', 'pts_per_hour_peers', 'pts_per_hour_pctile',
        'discharge_rate_me', 'discharge_rate_peers', 'discharge_rate_pctile',
        'icu_rate_me', 'icu_rate_peers', 'icu_rate_pctile',
        'rad_admit_me', 'rad_admit_peers', 'rad_disc_me', 'rad_disc_peers',
        'esi1', 'esi2', 'esi3', 'esi4', 'esi5',
        'billing_level3', 'billing_level4', 'billing_level5',
    ]
    col_list = ', '.join(['user_id', 'month', 'year'] + fields)
    placeholder_list = ', '.join(['?'] * (3 + len(fields)))
    update_list = ', '.join(f'{f} = excluded.{f}' for f in fields)
    values = [user_id, metrics['month'], metrics['year']] + [metrics.get(f) for f in fields]
    db.execute(
        f"""INSERT INTO monthly_metrics ({col_list}) VALUES ({placeholder_list})
            ON CONFLICT(user_id, month, year) DO UPDATE SET {update_list}""",
        values
    )
    # Invalidate all insight caches for this user
    db.execute('DELETE FROM insights_cache WHERE user_id = ?', (user_id,))
    db.commit()

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_page():
    if request.method == 'POST':
        file = request.files.get('pdf')
        if not file or file.filename == '':
            flash('Please select a PDF file.', 'error')
            return render_template('upload.html')
        if file.mimetype not in ALLOWED_MIME:
            flash('Only PDF files are accepted.', 'error')
            return render_template('upload.html')
        tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
        try:
            file.save(tmp.name)
            metrics = parse_metrics(tmp.name)
        except ParseError as e:
            flash(str(e), 'error')
            return render_template('upload.html')
        except Exception as e:
            flash('PDF appears to be password-protected or corrupted.', 'error')
            return render_template('upload.html')
        finally:
            tmp.close()
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        if not metrics.get('month') or not metrics.get('year'):
            flash('Could not determine month/year from this PDF.', 'error')
            return render_template('upload.html')
        _upsert_metrics(current_user.id, metrics)
        flash(f"Month {metrics['month']}/{metrics['year']} uploaded.", 'success')
        return redirect(url_for('dashboard', month=metrics['month'], year=metrics['year']))
    return render_template('upload.html')
```

- [ ] **Step 4: Create `templates/upload.html`**

```html
{% extends 'base.html' %}
{% block content %}
<main style="max-width:500px;margin:60px auto;padding:40px;background:#fff;border:1px solid #e2e8f0;border-radius:12px;">
  <h1 style="font-size:22px;font-weight:700;margin-bottom:8px;">Upload Monthly Metrics</h1>
  <p style="color:#64748b;font-size:14px;margin-bottom:24px;">Upload your ED Provider Metrics PDF. Each upload adds or updates one month of data.</p>
  <form method="post" enctype="multipart/form-data">
    <label style="display:block;font-size:14px;font-weight:600;margin-bottom:8px;">
      Select PDF
      <input type="file" name="pdf" accept=".pdf,application/pdf" required
             style="display:block;margin-top:6px;font-size:14px;">
    </label>
    <button type="submit" style="margin-top:16px;width:100%;padding:10px;background:#2563eb;color:#fff;border:none;border-radius:8px;font-size:14px;font-weight:700;font-family:inherit;cursor:pointer;">
      Upload &amp; Parse
    </button>
  </form>
  <p style="margin-top:16px;font-size:13px;text-align:center;color:#64748b;">
    <a href="{{ url_for('dashboard') }}">Back to dashboard</a>
  </p>
</main>
{% endblock %}
```

- [ ] **Step 5: Run upload tests**

```bash
pytest tests/test_upload.py -k "upload" -v
```
Expected: All upload tests PASS

- [ ] **Step 6: Commit**

```bash
git add app.py templates/upload.html tests/test_upload.py
git commit -m "feat: upload route with PDF parsing, upsert, and cache invalidation"
```

---

## Task 5: Dashboard Route + Data Structure

**Files:**
- Modify: `app.py` (full dashboard route)
- Create: `tests/test_dashboard.py`

- [ ] **Step 1: Write failing dashboard tests**

```python
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
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_dashboard.py -v
```
Expected: FAIL

- [ ] **Step 3: Update the dashboard route in `app.py`**

Replace the stub dashboard route with:

```python
import json
from calendar import month_abbr

MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

def _build_metrics_json(rows):
    """
    Convert list of monthly_metrics rows (sorted by year, month) into the
    const D = {...} structure expected by the dashboard Chart.js code.
    """
    def col(field):
        return [r[field] for r in rows]

    return {
        'patients':      {'me': col('patients')},
        'dischargeLOS':  {'me': col('discharge_los_me'), 'peers': col('discharge_los_peers'), 'pctile': col('discharge_los_pctile')},
        'admitLOS':      {'me': col('admit_los_me'), 'peers': col('admit_los_peers'), 'pctile': col('admit_los_pctile')},
        'admissionRate': {'me': col('admission_rate_me'), 'peers': col('admission_rate_peers'), 'pctile': col('admission_rate_pctile')},
        'bedRequest':    {'me': col('bed_request_me'), 'peers': col('bed_request_peers'), 'pctile': col('bed_request_pctile')},
        'returns72':     {'me': col('returns72_me'), 'peers': col('returns72_peers'), 'pctile': col('returns72_pctile')},
        'readmits72':    {'me': col('readmits72_me'), 'peers': col('readmits72_peers'), 'pctile': col('readmits72_pctile')},
        'radOrders':     {'me': col('rad_orders_me'), 'peers': col('rad_orders_peers'), 'pctile': col('rad_orders_pctile')},
        'labOrders':     {'me': col('lab_orders_me'), 'peers': col('lab_orders_peers'), 'pctile': col('lab_orders_pctile')},
        'ptsPerHour':    {'me': col('pts_per_hour_me'), 'peers': col('pts_per_hour_peers'), 'pctile': col('pts_per_hour_pctile')},
        'dischargeRate': {'me': col('discharge_rate_me'), 'peers': col('discharge_rate_peers'), 'pctile': col('discharge_rate_pctile')},
        'icuRate':       {'me': col('icu_rate_me'), 'peers': col('icu_rate_peers'), 'pctile': col('icu_rate_pctile')},
        'radByDispo': {
            'admitMe': col('rad_admit_me'), 'admitPeers': col('rad_admit_peers'),
            'discMe': col('rad_disc_me'), 'discPeers': col('rad_disc_peers'),
        },
        'esi': {
            'esi1': col('esi1'), 'esi2': col('esi2'), 'esi3': col('esi3'),
            'esi4': col('esi4'), 'esi5': col('esi5'),
        },
        'billing': {
            'level3': col('billing_level3'), 'level4': col('billing_level4'),
            'level5': col('billing_level5'),
        },
    }

@app.route('/dashboard')
@login_required
def dashboard():
    db = get_db()
    rows = db.execute(
        'SELECT * FROM monthly_metrics WHERE user_id = ? ORDER BY year, month',
        (current_user.id,)
    ).fetchall()
    rows = [dict(r) for r in rows]

    month_labels = [
        f"{MONTH_NAMES[r['month']]} {r['year']}" for r in rows
    ]
    month_list = [{'month': r['month'], 'year': r['year'], 'label': lbl}
                  for r, lbl in zip(rows, month_labels)]

    # Determine selected month index
    sel_month = request.args.get('month', type=int)
    sel_year = request.args.get('year', type=int)
    sel_idx = len(rows) - 1  # default to most recent
    if sel_month and sel_year:
        for i, r in enumerate(rows):
            if r['month'] == sel_month and r['year'] == sel_year:
                sel_idx = i
                break

    metrics_json = _build_metrics_json(rows) if rows else {}
    selected = rows[sel_idx] if rows else None

    return render_template(
        'dashboard.html',
        has_data=bool(rows),
        metrics_json=metrics_json,
        month_labels=month_labels,
        month_list=month_list,
        sel_idx=sel_idx,
        selected=selected,
        username=current_user.username,
    )
```

- [ ] **Step 4: Run dashboard tests**

```bash
pytest tests/test_dashboard.py -v
```
Expected: All 4 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_dashboard.py
git commit -m "feat: dashboard route with data aggregation and month selection"
```

---

## Task 6: Dashboard Template (Chart.js)

**Files:**
- Modify: `templates/dashboard.html` (adapt ED_Provider_Dashboard.html to Jinja2)
- Modify: `templates/base.html` (add month selector to nav)

This is the largest task. The approach: copy the existing `ED_Provider_Dashboard.html` verbatim, then make targeted modifications.

- [ ] **Step 1: Copy the existing dashboard HTML as the starting template**

```bash
cp "/Users/branjoho/Documents/Attending metrics/ED_Provider_Dashboard.html" \
   /Users/branjoho/Documents/Claude/claude_test/ed-metrics/templates/dashboard.html
```

- [ ] **Step 2: Add Jinja2 template inheritance wrapper**

Open `templates/dashboard.html` and wrap the entire content:
- Remove the `<!DOCTYPE html>`, `<html>`, `<head>`, `<body>` tags
- Add `{% extends 'base.html' %}` at the very top
- Wrap everything in `{% block content %}` ... `{% endblock %}`
- Move the `<style>` block into a `{% block head %}{% endblock %}` that base.html supports

Update `templates/base.html` to include the head block:
```html
<head>
...
{% block head %}{% endblock %}
</head>
```

- [ ] **Step 3: Replace the hardcoded data block with Jinja2-injected data**

Find this section in the JS (around line 840 in the original):
```javascript
const months = ['Sep 2025','Oct 2025',...];
const S = ['Sep','Oct',...];
const D = { ... };
```

Replace with:
```javascript
const months = {{ month_labels | tojson | safe }};
const S = months.map(m => m.split(' ')[0]);
const D = {{ metrics_json | tojson | safe }};
const selIdx = {{ sel_idx }};
```

- [ ] **Step 4: Update the page header to show the logged-in user and date range**

Find:
```html
<h1>ED Provider Metrics — Brandon Ho, MD</h1>
<p>Seattle Children's Hospital · Emergency Department · You vs. Peer Attendings</p>
<span class="range-badge">Sep 2025 – Feb 2026 &nbsp;·&nbsp; 6-month view</span>
```

Replace with:
```html
<h1>ED Provider Metrics — {{ username }}</h1>
<p>Seattle Children's Hospital · Emergency Department · You vs. Peer Attendings</p>
{% if month_list %}
<span class="range-badge">
  {{ month_list[0].label }} – {{ month_list[-1].label }}
  &nbsp;·&nbsp; {{ month_list|length }}-month view
</span>
{% endif %}
```

- [ ] **Step 5: Add month selector to nav and handle empty state**

At the top of `{% block content %}`, before `<nav>`, add:

```html
{% if not has_data %}
<div style="max-width:600px;margin:80px auto;text-align:center;padding:40px;">
  <h2 style="font-size:22px;font-weight:700;margin-bottom:12px;">No data yet</h2>
  <p style="color:#64748b;margin-bottom:24px;">Upload your first ED Provider Metrics PDF to get started.</p>
  <a href="{{ url_for('upload_page') }}" style="display:inline-block;padding:12px 28px;background:#2563eb;color:#fff;border-radius:8px;font-weight:700;text-decoration:none;">
    Upload PDF
  </a>
</div>
{% else %}
... (all the existing dashboard HTML) ...
{% endif %}
```

In `templates/base.html`, add a month selector to the nav (shown only when `month_list` is available):
```html
{% if current_user.is_authenticated and month_list is defined and month_list %}
<select onchange="window.location='/dashboard?month='+this.value.split('/')[0]+'&year='+this.value.split('/')[1]"
        style="margin:0 12px;padding:5px 10px;border:1px solid #e2e8f0;border-radius:6px;font-size:13px;">
  {% for m in month_list %}
  <option value="{{ m.month }}/{{ m.year }}"
    {% if loop.index0 == sel_idx %}selected{% endif %}>
    {{ m.label }}
  </option>
  {% endfor %}
</select>
{% endif %}
```

- [ ] **Step 6: Replace hardcoded insight drawers with fetch-based loading**

The existing HTML has hardcoded insight content inside each `.insight-drawer`. Replace all hardcoded insight content with a loading placeholder:

Find each block like:
```html
<div class="insight-drawer" id="ins-dischargeLOS"><div class="insight-inner">
  <div class="insight-item">...</div>
  ...
</div></div>
```

Replace with:
```html
<div class="insight-drawer" id="ins-dischargeLOS">
  <div class="insight-inner" id="ins-content-dischargeLOS">
    <p style="color:#64748b;font-size:13px;padding:8px 0;">Loading insights...</p>
  </div>
</div>
```

Do this for all chart insight drawers: dischargeLOS, admitLOS, bedRequest, admissionRate, radByDispo, labOrders, returns72, readmits72, icuRate, volume, ptsPerHour, dischargeRate, esiChart, pctTable, overview (auto summary).

- [ ] **Step 7: Add JavaScript to fetch insights on drawer open**

Add this to the `<script>` block in dashboard.html, near the `toggleInsight` function:

```javascript
// Override toggleInsight to fetch LLM insights on first open
const _loadedInsights = new Set();
function toggleInsight(btn) {
  const targetId = btn.dataset.target;
  const drawer = document.getElementById(targetId);
  const isOpen = drawer.classList.contains('open');
  // Close all
  document.querySelectorAll('.insight-drawer.open').forEach(d => d.classList.remove('open'));
  document.querySelectorAll('.insight-btn.open').forEach(b => b.classList.remove('open'));
  if (!isOpen) {
    drawer.classList.add('open');
    btn.classList.add('open');
    // Fetch insights if not yet loaded
    const chartKey = targetId.replace('ins-', '');
    if (!_loadedInsights.has(chartKey)) {
      _loadedInsights.add(chartKey);
      const selMonth = months[selIdx] || '';
      const parts = selMonth.split(' ');
      const monthNum = new Date(Date.parse(parts[0] + ' 1')).getMonth() + 1;
      const year = parts[1];
      const contentEl = document.getElementById('ins-content-' + chartKey);
      fetch(`/api/insights/${chartKey}/${monthNum}/${year}`)
        .then(r => r.json())
        .then(data => {
          if (data.error) {
            contentEl.innerHTML = `<p style="color:#dc2626;font-size:13px;">${data.error} <button onclick="_loadedInsights.delete('${chartKey}');toggleInsight(document.querySelector('[data-target=ins-${chartKey}]'))" style="background:none;border:none;color:#2563eb;cursor:pointer;font-size:13px;">Retry</button></p>`;
            return;
          }
          contentEl.innerHTML = data.map(item => `
            <div class="insight-item">
              <div class="insight-sev sev-${item.severity}"></div>
              <div class="insight-text">${item.text}
                ${item.tags && item.tags.length ? '<div class="insight-tags">' + item.tags.map(t => `<span class="itag itag-${t}">${t}</span>`).join('') + '</div>' : ''}
              </div>
            </div>
          `).join('');
        })
        .catch(() => {
          contentEl.innerHTML = `<p style="color:#dc2626;font-size:13px;">Failed to load insights.</p>`;
        });
    }
  }
}
```

- [ ] **Step 8: Update KPI card values to use selected month data**

The existing dashboard uses hardcoded values for KPI cards. Update the KPI cards to reference Jinja2 variables for the selected month:

```html
<!-- Example KPI card pattern — apply to all 12 cards -->
<div class="kpi-card" style="--color:#2563eb" id="kpi-patients">
  <div class="kpi-label">Patients Seen</div>
  <div class="kpi-value">{{ selected.patients or '—' }}</div>
  <div class="kpi-sub">All peers: (peer total not in PDF)</div>
  {% if selected.discharge_los_pctile %}
    <div class="kpi-pct pct-{{ 'good' if selected.discharge_los_pctile < 33 else ('bad' if selected.discharge_los_pctile > 66 else 'mid') }}">
      {{ selected.discharge_los_pctile|round(0)|int }}th pct
    </div>
  {% endif %}
</div>
```

Apply this pattern to all 12 KPI cards, using the appropriate `selected.*` field for each card.

- [ ] **Step 9: Update the auto-summary section**

The "Performance Summary" auto-summary block currently calls `buildSummary()` with hardcoded data. Update it to use the injected `D` and `selIdx` variables. The existing JS `buildSummary()` function should work as-is once `D` and `selIdx` are defined correctly.

- [ ] **Step 10: Verify the dashboard renders correctly in browser**

```bash
cd /Users/branjoho/Documents/Claude/claude_test/ed-metrics
python app.py
```
Open http://127.0.0.1:5000, register an account, upload a real PDF, verify:
- Dashboard shows correct KPI values
- All 5 sections render
- Chart.js charts appear with data
- Month selector works
- Goals panel opens and saves

- [ ] **Step 11: Commit**

```bash
git add templates/ static/
git commit -m "feat: dashboard Jinja2 template with Chart.js and dynamic insights loading"
```

---

## Task 7: LLM Insights API

**Files:**
- Modify: `app.py` (add insights route)
- Create: `tests/test_insights.py`

- [ ] **Step 1: Write failing insights tests**

```python
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
    db = sqlite3.connect(app_module.DATABASE)
    count = db.execute("SELECT COUNT(*) FROM insights_cache").fetchone()[0]
    assert count == 0
    db.close()
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_insights.py -v
```
Expected: FAIL

- [ ] **Step 3: Add LLM insights route to `app.py`**

Add these imports at the top:
```python
import anthropic
from flask import jsonify
```

Add after app init:
```python
_api_key = os.environ.get('ANTHROPIC_API_KEY')
anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None
```

Add the chart context definitions and route:

```python
CHART_CONTEXTS = {
    'dischargeLOS':  ('Discharge Time (Hours)', 'discharge_los_me', 'discharge_los_peers', 'discharge_los_pctile', 'Lower = faster. Percentile: lower = better than peers.'),
    'admitLOS':      ('Admitted Patient Wait Time (Hours)', 'admit_los_me', 'admit_los_peers', 'admit_los_pctile', 'Time from arrival to leaving ED for inpatient bed. Lower = better.'),
    'admissionRate': ('Admission Rate (%)', 'admission_rate_me', 'admission_rate_peers', 'admission_rate_pctile', 'Percent of patients admitted. Context: watch alongside readmit rate.'),
    'bedRequest':    ('Time to Bed Request (Minutes)', 'bed_request_me', 'bed_request_peers', 'bed_request_pctile', 'How quickly bed request initiated after arrival. Lower = better.'),
    'returns72':     ('72-Hour Return Rate (%)', 'returns72_me', 'returns72_peers', 'returns72_pctile', 'Unplanned returns within 3 days. Lower = better. Target <3.5%.'),
    'readmits72':    ('72-Hour Readmit Rate (%)', 'readmits72_me', 'readmits72_peers', 'readmits72_pctile', 'Returns that resulted in admission — highest-severity safety signal. Lower = better.'),
    'icuRate':       ('ICU Admission Rate (%)', 'icu_rate_me', 'icu_rate_peers', 'icu_rate_pctile', 'How often admitted patients required intensive care.'),
    'radOrders':     ('Radiology Orders (%)', 'rad_orders_me', 'rad_orders_peers', 'rad_orders_pctile', 'How often imaging was ordered across all patients.'),
    'labOrders':     ('Lab Orders (%)', 'lab_orders_me', 'lab_orders_peers', 'lab_orders_pctile', 'How often labs were ordered.'),
    'ptsPerHour':    ('Patients Per Hour', 'pts_per_hour_me', 'pts_per_hour_peers', 'pts_per_hour_pctile', 'New patients taken on per hour. Higher = more productive.'),
    'dischargeRate': ('Discharge Rate (%)', 'discharge_rate_me', 'discharge_rate_peers', 'discharge_rate_pctile', 'Percent of patients discharged (not admitted). Higher = better for throughput.'),
    'volume':        ('Patients Seen Per Month', 'patients', None, None, 'Total patients you were first attending on.'),
}

def _build_insights_prompt(chart_key, sel_row, all_rows):
    ctx = CHART_CONTEXTS.get(chart_key)
    if not ctx:
        return None
    chart_name, me_field, peers_field, pctile_field, description = ctx

    this_month = f"{MONTH_NAMES[sel_row['month']]} {sel_row['year']}"
    me_val = sel_row.get(me_field)
    peers_val = sel_row.get(peers_field) if peers_field else None
    pctile_val = sel_row.get(pctile_field) if pctile_field else None

    trend_rows = []
    for r in all_rows:
        lbl = f"{MONTH_NAMES[r['month']]} {r['year']}"
        v = r.get(me_field)
        p = r.get(peers_field) if peers_field else None
        pct = r.get(pctile_field) if pctile_field else None
        trend_rows.append(f"  {lbl}: you={v}, peers={p}, pctile={pct}")
    trend = '\n'.join(trend_rows)

    return f"""You are analyzing ED provider performance data from Seattle Children's Hospital.

Chart: {chart_name}
Context: {description}

This month ({this_month}):
- Provider value: {me_val}
- Peer average: {peers_val}
- Percentile: {pctile_val}

Trend across all uploaded months:
{trend}

Generate 2-4 concise insights. Each insight must have:
- severity: one of "alert", "warn", "good", "neutral"
- text: 1-2 sentences of plain text (no markdown)
- tags: list of 0-2 tags from ["trend", "bench", "pos", "safety"]

Return ONLY a valid JSON array, no markdown:
[{{"severity": "...", "text": "...", "tags": [...]}}]"""

@app.route('/api/insights/<chart_key>/<int:month>/<int:year>')
@login_required
def get_insights(chart_key, month, year):
    if not anthropic_client:
        return jsonify({'error': 'Insights unavailable — API key not configured.'})

    db = get_db()

    # Check cache
    from datetime import datetime, timezone, timedelta
    cached = db.execute(
        'SELECT insight_text, generated_at FROM insights_cache WHERE user_id=? AND month=? AND year=? AND chart_key=?',
        (current_user.id, month, year, chart_key)
    ).fetchone()
    if cached:
        generated_at = datetime.fromisoformat(cached['generated_at'])
        if datetime.now(timezone.utc) - generated_at < timedelta(days=90):
            return jsonify(json.loads(cached['insight_text']))

    # Fetch all rows for trend context
    all_rows = [dict(r) for r in db.execute(
        'SELECT * FROM monthly_metrics WHERE user_id=? ORDER BY year, month',
        (current_user.id,)
    ).fetchall()]
    sel_row = next((r for r in all_rows if r['month'] == month and r['year'] == year), None)
    if not sel_row:
        return jsonify({'error': 'No data found for this month.'})

    prompt = _build_insights_prompt(chart_key, sel_row, all_rows)
    if not prompt:
        return jsonify({'error': f'Unknown chart key: {chart_key}'})

    try:
        message = anthropic_client.messages.create(
            model='claude-sonnet-4-6',
            max_tokens=1024,
            temperature=0.3,
            messages=[{'role': 'user', 'content': prompt}]
        )
        raw = message.content[0].text.strip()
        if raw.startswith('```'):
            raw = raw.split('```')[1]
            if raw.startswith('json'):
                raw = raw[4:]
        insights = json.loads(raw)
    except Exception as e:
        return jsonify({'error': f'Could not generate insights. Please try again.'})

    # Cache it
    db.execute(
        '''INSERT INTO insights_cache (user_id, month, year, chart_key, insight_text, generated_at)
           VALUES (?, ?, ?, ?, ?, ?)
           ON CONFLICT(user_id, month, year, chart_key) DO UPDATE SET
           insight_text=excluded.insight_text, generated_at=excluded.generated_at''',
        (current_user.id, month, year, chart_key,
         json.dumps(insights), datetime.now(timezone.utc).isoformat())
    )
    db.commit()
    return jsonify(insights)
```

- [ ] **Step 4: Run insights tests**

```bash
pytest tests/test_insights.py -v
```
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add app.py tests/test_insights.py
git commit -m "feat: LLM insights API with caching via Claude claude-sonnet-4-6"
```

---

## Task 8: Delete Month

**Files:**
- Modify: `app.py` (add DELETE route)
- Create: `tests/test_delete.py`

- [ ] **Step 1: Write failing delete tests**

```python
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
            'pdf': (io.BytesIO(b'%PDF-1.4 fake'), 'test.pdf', 'application/pdf')
        }, content_type='multipart/form-data')

def test_delete_month_removes_row(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    rv = client.delete('/api/months/2/2026')
    assert rv.status_code == 200
    db = sqlite3.connect(app_module.DATABASE)
    row = db.execute('SELECT * FROM monthly_metrics WHERE month=2 AND year=2026').fetchone()
    assert row is None
    db.close()

def test_delete_cascades_insights_cache(client):
    register_user(client)
    login_user(client)
    upload_month(client)
    # Manually insert a cache row
    db = sqlite3.connect(app_module.DATABASE)
    user = db.execute("SELECT id FROM users WHERE username='testuser'").fetchone()
    db.execute("INSERT INTO insights_cache (user_id, month, year, chart_key, insight_text, generated_at) VALUES (?,2,2026,'dischargeLOS','[]','2026-01-01')", (user[0],))
    db.commit()
    db.close()
    client.delete('/api/months/2/2026')
    db = sqlite3.connect(app_module.DATABASE)
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
    db = sqlite3.connect(app_module.DATABASE)
    user1 = db.execute("SELECT id FROM users WHERE username='user1'").fetchone()
    row = db.execute('SELECT * FROM monthly_metrics WHERE user_id=? AND month=2 AND year=2026', (user1[0],)).fetchone()
    assert row is not None
    db.close()

def test_delete_nonexistent_month_returns_404(client):
    register_user(client)
    login_user(client)
    rv = client.delete('/api/months/12/2020')
    assert rv.status_code == 404
```

- [ ] **Step 2: Run to confirm tests fail**

```bash
pytest tests/test_delete.py -v
```
Expected: FAIL

- [ ] **Step 3: Add DELETE route to `app.py`**

```python
@app.route('/api/months/<int:month>/<int:year>', methods=['DELETE'])
@login_required
def delete_month(month, year):
    db = get_db()
    row = db.execute(
        'SELECT id FROM monthly_metrics WHERE user_id=? AND month=? AND year=?',
        (current_user.id, month, year)
    ).fetchone()
    if not row:
        return jsonify({'error': 'Not found'}), 404
    db.execute(
        'DELETE FROM insights_cache WHERE user_id=? AND month=? AND year=?',
        (current_user.id, month, year)
    )
    db.execute(
        'DELETE FROM monthly_metrics WHERE user_id=? AND month=? AND year=?',
        (current_user.id, month, year)
    )
    db.commit()
    return jsonify({'ok': True})
```

- [ ] **Step 4: Run delete tests**

```bash
pytest tests/test_delete.py -v
```
Expected: All 4 tests PASS

- [ ] **Step 5: Run full test suite**

```bash
pytest tests/ -v
```
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add app.py tests/test_delete.py
git commit -m "feat: DELETE month endpoint with cascade delete of insights cache"
```

---

## Final Verification

- [ ] **Run full test suite**

```bash
pytest tests/ -v --tb=short
```
Expected: All tests PASS

- [ ] **Smoke test with real PDFs**

```bash
python app.py
```
1. Register an account at http://127.0.0.1:5000
2. Upload each PDF from `/Users/branjoho/Documents/Attending metrics/`
3. Verify dashboard shows 6 months of data with correct KPI values
4. Open each chart's Insights drawer (requires ANTHROPIC_API_KEY in .env)
5. Verify goals panel saves and shows dashed lines
6. Verify month selector switches between months

- [ ] **Final commit**

```bash
git add -A
git commit -m "feat: complete ED provider metrics dashboard web app"
```
