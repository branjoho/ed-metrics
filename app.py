import os
import re
import sqlite3
import tempfile
from datetime import datetime, timezone
from flask import Flask, g, current_app, render_template, redirect, url_for, flash, request, jsonify
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from parse_pdf import parse_metrics, ParseError

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB
app.config['DATABASE'] = os.path.join(app.instance_path, 'metrics.db')

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

os.makedirs(app.instance_path, exist_ok=True)


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
        g.db = sqlite3.connect(
            current_app.config['DATABASE'],
            detect_types=sqlite3.PARSE_DECLTYPES
        )
        g.db.row_factory = sqlite3.Row
        g.db.execute("PRAGMA foreign_keys = ON")
    return g.db

@app.teardown_appcontext
def close_db(e=None):
    db = g.pop('db', None)
    if db is not None:
        db.close()

def init_db():
    # Must be called within an app context
    db = sqlite3.connect(current_app.config['DATABASE'])
    db.execute("PRAGMA foreign_keys = ON")
    db.executescript(SCHEMA)
    db.commit()
    db.close()

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
            error = 'Username must be 3\u201332 characters (letters, numbers, underscores only).'
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
    sel_idx = len(rows) - 1 if rows else 0  # default to most recent; 0 if empty
    if sel_month and sel_year:
        for i, r in enumerate(rows):
            if r['month'] == sel_month and r['year'] == sel_year:
                sel_idx = i
                break

    metrics_json = _build_metrics_json(rows) if rows else {}
    selected = dict(rows[sel_idx]) if rows else None
    if selected:
        # Add derived/display fields not stored in the DB
        selected.setdefault('patients_peers', None)
        selected.setdefault('patients_pctile', None)
        selected['month_label'] = (
            f"{MONTH_NAMES[selected['month']]} {selected['year']}"
        )

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

ALLOWED_MIME = {'application/pdf'}

METRIC_FIELDS = [
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
    'rad_admit_me', 'rad_admit_peers',
    'rad_disc_me', 'rad_disc_peers',
    'esi1', 'esi2', 'esi3', 'esi4', 'esi5',
    'billing_level3', 'billing_level4', 'billing_level5',
]

def _upsert_metrics(user_id, metrics):
    db = get_db()
    col_list = ', '.join(['user_id', 'month', 'year'] + METRIC_FIELDS)
    placeholder_list = ', '.join(['?'] * (3 + len(METRIC_FIELDS)))
    update_list = ', '.join(f'{f} = excluded.{f}' for f in METRIC_FIELDS)
    values = [user_id, metrics['month'], metrics['year']] + [metrics.get(f) for f in METRIC_FIELDS]
    db.execute(
        f"""INSERT INTO monthly_metrics ({col_list}) VALUES ({placeholder_list})
            ON CONFLICT(user_id, month, year) DO UPDATE SET {update_list}""",
        values
    )
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
            tmp.close()
            metrics = parse_metrics(tmp.name)
        except ParseError as e:
            flash(str(e), 'error')
            return render_template('upload.html')
        except Exception:
            flash('PDF appears to be password-protected or corrupted.', 'error')
            return render_template('upload.html')
        finally:
            try:
                tmp.close()  # no-op if already closed; guards against save() failure
            except Exception:
                pass
            try:
                os.unlink(tmp.name)
            except OSError:
                pass
        if not metrics.get('month') or not metrics.get('year'):
            flash('Could not determine month/year from this PDF.', 'error')
            return render_template('upload.html')
        _upsert_metrics(current_user.id, metrics)
        flash(f"Month {metrics['month']}/{metrics['year']} uploaded successfully.", 'success')
        return redirect(url_for('dashboard', month=metrics['month'], year=metrics['year']))
    return render_template('upload.html')

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


if __name__ == '__main__':
    init_db()
    app.run(debug=True)
