import os
import re
import json
import sqlite3
import tempfile
import anthropic
from datetime import datetime, timezone, timedelta
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

_api_key = os.environ.get('ANTHROPIC_API_KEY')
anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None


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
    'radByDispo':    ('Radiology by Disposition', 'rad_admit_me', 'rad_admit_peers', None, 'Radiology ordering split by admitted vs discharged patients. Admitted patients typically require more imaging.'),
    'esiChart':      ('ESI Acuity Mix', 'esi3', None, None, 'Distribution across ESI levels: 1=critical, 2=emergent, 3=urgent, 4=semi-urgent, 5=non-urgent. ESI-3 is typically the largest group.'),
    'pctTable':      ('Overall Percentile Rankings', 'discharge_los_pctile', None, None, 'Summary of all metric percentile rankings. Lower percentile = better for time/rate metrics; higher = better for productivity.'),
    'overview':      ('Overall Performance Summary', 'discharge_los_pctile', None, None, 'High-level snapshot of this month\'s performance across all key metrics relative to peers.'),
}

def _build_overview_prompt(sel_row, all_rows):
    this_month = f"{MONTH_NAMES[sel_row['month']]} {sel_row['year']}"

    def v(field):
        val = sel_row.get(field)
        return '—' if val is None else val

    snapshot = f"""Discharge LOS: {v('discharge_los_me')}h (peers: {v('discharge_los_peers')}h, pctile: {v('discharge_los_pctile')})
Admitted LOS: {v('admit_los_me')}h (peers: {v('admit_los_peers')}h, pctile: {v('admit_los_pctile')})
Admission Rate: {v('admission_rate_me')}% (peers: {v('admission_rate_peers')}%, pctile: {v('admission_rate_pctile')})
Bed Request Time: {v('bed_request_me')} min (peers: {v('bed_request_peers')} min, pctile: {v('bed_request_pctile')})
72-Hr Return Rate: {v('returns72_me')}% (peers: {v('returns72_peers')}%, pctile: {v('returns72_pctile')})
72-Hr Readmit Rate: {v('readmits72_me')}% (peers: {v('readmits72_peers')}%, pctile: {v('readmits72_pctile')})
Radiology Orders: {v('rad_orders_me')}% (peers: {v('rad_orders_peers')}%, pctile: {v('rad_orders_pctile')})
Lab Orders: {v('lab_orders_me')}% (peers: {v('lab_orders_peers')}%, pctile: {v('lab_orders_pctile')})
Patients/Hour: {v('pts_per_hour_me')} (peers: {v('pts_per_hour_peers')}, pctile: {v('pts_per_hour_pctile')})
Discharge Rate: {v('discharge_rate_me')}% (peers: {v('discharge_rate_peers')}%, pctile: {v('discharge_rate_pctile')})
ICU Rate: {v('icu_rate_me')}% (peers: {v('icu_rate_peers')}%, pctile: {v('icu_rate_pctile')})
Total Patients: {v('patients')}
ESI Mix: 1={v('esi1')}%, 2={v('esi2')}%, 3={v('esi3')}%, 4={v('esi4')}%, 5={v('esi5')}%
Billing: L3={v('billing_level3')}%, L4={v('billing_level4')}%, L5={v('billing_level5')}%"""

    trend_rows = []
    for r in all_rows:
        lbl = f"{MONTH_NAMES[r['month']]} {r['year']}"
        trend_rows.append(
            f"  {lbl}: readmit={r.get('readmits72_me')} (pctile {r.get('readmits72_pctile')}), "
            f"return={r.get('returns72_me')} (pctile {r.get('returns72_pctile')}), "
            f"dischLOS={r.get('discharge_los_me')} (pctile {r.get('discharge_los_pctile')}), "
            f"pts/hr={r.get('pts_per_hour_me')} (pctile {r.get('pts_per_hour_pctile')})"
        )
    trend = '\n'.join(trend_rows)

    return f"""You are analyzing ED provider performance data from Seattle Children's Hospital.

Generate an overall performance summary for {this_month}.

Metric context:
- Discharge LOS, bed request time, return/readmit rates: lower percentile = better than peers
- Patients/hour, discharge rate: higher percentile = better
- 72-hr readmit rate is the highest-severity safety signal
- Low admission rate combined with high readmit rate is a concern (undertriaging)

This month ({this_month}) — all metrics with peer comparisons and percentile rankings:
{snapshot}

Trend across all uploaded months (key indicators):
{trend}

Generate 3-5 concise insights that together form a complete performance summary. Include:
- Top 1-2 strengths (use severity "good")
- Top 1-2 concerns, prioritizing safety signals (use severity "alert" or "warn")
- 1 specific, actionable recommendation (use severity "neutral")

Each insight must have:
- severity: one of "alert", "warn", "good", "neutral"
- text: 1-2 sentences of plain text (no markdown)
- tags: list of 0-2 tags from ["trend", "bench", "pos", "safety"]

Return ONLY a valid JSON array, no markdown:
[{{"severity": "...", "text": "...", "tags": [...]}}]"""


def _build_insights_prompt(chart_key, sel_row, all_rows):
    if chart_key == 'overview':
        return _build_overview_prompt(sel_row, all_rows)

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

    # Check cache (valid for 90 days)
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
    except Exception:
        return jsonify({'error': 'Could not generate insights. Please try again.'})

    # Cache result
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

def _process_upload(file):
    """Parse a single uploaded file. Returns metrics dict or raises ParseError / Exception."""
    tmp = tempfile.NamedTemporaryFile(suffix='.pdf', delete=False)
    try:
        file.save(tmp.name)
        tmp.close()
        return parse_metrics(tmp.name)
    finally:
        try:
            tmp.close()
        except Exception:
            pass
        try:
            os.unlink(tmp.name)
        except OSError:
            pass

@app.route('/upload', methods=['GET', 'POST'])
@login_required
def upload_page():
    if request.method == 'POST':
        files = request.files.getlist('pdfs')
        files = [f for f in files if f and f.filename]
        if not files:
            flash('Please select at least one PDF file.', 'error')
            return render_template('upload.html')

        last_month, last_year = None, None
        for file in files:
            if file.mimetype not in ALLOWED_MIME:
                flash(f'{file.filename}: only PDF files are accepted.', 'error')
                continue
            try:
                metrics = _process_upload(file)
            except ParseError as e:
                flash(f'{file.filename}: {e}', 'error')
                continue
            except Exception:
                flash(f'{file.filename}: PDF appears to be password-protected or corrupted.', 'error')
                continue
            if not metrics.get('month') or not metrics.get('year'):
                flash(f'{file.filename}: could not determine month/year. Rename to MM_YYYY format or ensure the PDF is unmodified.', 'error')
                continue
            _upsert_metrics(current_user.id, metrics)
            flash(f"{MONTH_NAMES[metrics['month']]} {metrics['year']} uploaded.", 'success')
            last_month, last_year = metrics['month'], metrics['year']

        if last_month:
            return redirect(url_for('dashboard', month=last_month, year=last_year))
        return render_template('upload.html')
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
    with app.app_context():
        init_db()
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
