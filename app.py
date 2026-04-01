import os
import re
import json
import tempfile
import anthropic
from datetime import datetime, timezone, timedelta
from flask import Flask, current_app, render_template, redirect, url_for, flash, request, jsonify, Response
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from flask_bcrypt import Bcrypt
from dotenv import load_dotenv
from parse_pdf import parse_metrics, ParseError
import flask_db

load_dotenv()

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get('SECRET_KEY', 'dev-secret-change-me')
app.config['MAX_CONTENT_LENGTH'] = 20 * 1024 * 1024  # 20 MB

bcrypt = Bcrypt(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

_api_key = os.environ.get('ANTHROPIC_API_KEY')
anthropic_client = anthropic.Anthropic(api_key=_api_key) if _api_key else None


class User(UserMixin):
    def __init__(self, id, username):
        self.id = id
        self.username = username

@login_manager.user_loader
def load_user(user_id):
    row = flask_db.get_user_by_id(int(user_id))
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
        if flask_db.get_user(username):
            flash('Username already taken.', 'error')
            return render_template('register.html', username=username)
        flask_db.create_user(username, pw_hash)
        flash('Account created. Please log in.', 'success')
        return redirect(url_for('login'))
    return render_template('register.html')

@app.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')
        row = flask_db.get_user(username)
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

    return f"""You are writing a monthly performance summary for an emergency medicine physician at Seattle Children's Hospital.

FORMAT — every insight must follow this exact pattern:
<strong>One punchy headline sentence that states the key finding.</strong> One or two supporting sentences with specific numbers (e.g. "faster than 87% of peers", "4 of 6 months", "peer avg 1.2%").

EXAMPLES of the correct style:
- Good: <strong>Your discharge time is your clearest strength this month.</strong> At 3.47h you were faster than 87% of your peers — the best percentile you've hit all year.
- Warn: <strong>Your readmit rate has been above the 65th percentile in 4 of 6 months.</strong> In {this_month} it was 1.6% vs a peer average of 1.2%. A patient who returns within 3 days and gets admitted very likely needed to stay the first time.
- Alert: <strong>Low admission rate combined with a high readmit rate is an undertriage signal.</strong> You admitted 6 points fewer patients than peers while readmitting at the 75th percentile — some patients sent home likely needed to stay.
- Neutral: <strong>Action: pull your {this_month} 72-hour readmission cases.</strong> Identify the top 2–3 diagnoses — that's the fastest way to find where your discharge threshold needs adjustment.

STRUCTURE — return exactly 3-4 insights in this order:
1. Top strength ("good") — best metric vs peers this month, with the number
2. Most pressing concern ("alert" or "warn") — prioritize safety signals (readmit > return > throughput), with exact values
3. Supporting context ("warn" or "neutral") — second concern or pattern across months, if meaningful
4. One specific action ("neutral") — what to do about the concern; must be concrete, not generic

RULES:
- If readmit rate > 65th pct AND admission rate < peers, flag the undertriage combination explicitly
- Use exact numbers from the data — percentile, your value, peer value
- No filler: no "it's worth noting", "overall", "importantly"
- HTML bold tags only — no markdown asterisks, no bullet points in the text field

Metric context:
- Lower percentile = better: Discharge LOS, Admitted LOS, Bed Request, Return Rate, Readmit Rate
- Higher percentile = better: Patients/Hour, Discharge Rate
- 72-hr readmit rate is the highest-severity safety signal

{this_month} data:
{snapshot}

Trend (for context — focus summary on {this_month}):
{trend}

Each insight must have:
- severity: "alert", "warn", "good", or "neutral"
- text: formatted as shown above with <strong>bold headline.</strong> followed by supporting detail

Return ONLY a valid JSON array, no markdown:
[{{"severity": "...", "text": "..."}}]"""


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

    return f"""You are writing chart insights for an emergency medicine physician at Seattle Children's Hospital.

FORMAT — every insight must follow this pattern:
<strong>One punchy headline that states the key finding.</strong> 1-2 supporting sentences with specific numbers.

EXAMPLES of the correct style:
- <strong>This is a structural pattern, not a one-bad-month problem.</strong> You've been above the 65th percentile in 4 of 6 months. Peers average 0.6–1.2%; your range has been 1.0–1.7% in affected months.
- <strong>You're in the top 10% for throughput in your best months.</strong> This is a genuine strength — you take on patients quickly.
- <strong>November was your worst month across the whole dataset.</strong> At 5.8% returns it was worse than 90% of peers and nearly double the 3.5% target.
- <strong>Action: pull your readmission cases and look for the top 2–3 diagnoses.</strong> A focused chart review of 5–10 cases will reveal whether there's a pattern in diagnosis, time-of-day, or discharge plan gaps.

Chart: {chart_name}
Context: {description}

{this_month}: you={me_val}, peers={peers_val}, percentile={pctile_val}
Trend:
{trend}

Write 2-3 insights for this chart. Note whether this month is a pattern or a one-time event. Include a specific action if there is a concern.

Each insight must have:
- severity: "alert" (urgent), "warn" (concern), "good" (strength), "neutral" (context/action)
- text: <strong>bold headline.</strong> followed by supporting detail with exact numbers

Return ONLY a valid JSON array, no markdown:
[{{"severity": "...", "text": "..."}}]"""

@app.route('/api/insights/<chart_key>/<int:month>/<int:year>')
@login_required
def get_insights(chart_key, month, year):
    if not anthropic_client:
        return jsonify({'error': 'Insights unavailable — API key not configured.'})

    cached = flask_db.get_cached_insight(current_user.id, month, year, chart_key)
    if cached is not None:
        return jsonify(cached)

    all_rows = flask_db.get_metrics(current_user.id)
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
        app.logger.error('Insights error for %s: %s', chart_key, e)
        return jsonify({'error': f'Could not generate insights: {e}'})

    flask_db.save_insight_cache(current_user.id, month, year, chart_key, insights)
    return jsonify(insights)

def _build_metrics_json(rows):
    """
    Convert list of monthly_metrics rows (sorted by year, month) into the
    const D = {...} structure expected by the dashboard Chart.js code.
    """
    def col(field):
        return [r[field] for r in rows]

    return {
        'patients':      {'me': col('patients'), 'shifts': col('shift_count')},
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
        'labByDispo': {
            'admitMe': col('lab_admit_me'), 'admitPeers': col('lab_admit_peers'),
            'discMe': col('lab_disc_me'), 'discPeers': col('lab_disc_peers'),
        },
        'esi': {
            'esi1': col('esi1'), 'esi2': col('esi2'), 'esi3': col('esi3'),
            'esi4': col('esi4'), 'esi5': col('esi5'),
        },
        'billing': {
            'level3': col('billing_level3'), 'level4': col('billing_level4'),
            'level5': col('billing_level5'),
        },
        'shiftByMonth': [
            json.loads(r.get('shift_data') or '[]') for r in rows
        ],
    }

@app.route('/dashboard')
@login_required
def dashboard():
    rows = flask_db.get_metrics(current_user.id)

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
        # Deserialize shift_data JSON for template use
        raw_shift = selected.get('shift_data')
        selected['shift_data'] = json.loads(raw_shift) if raw_shift else []

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
    'lab_admit_me', 'lab_admit_peers',
    'lab_disc_me', 'lab_disc_peers',
    'shift_count',
    'esi1', 'esi2', 'esi3', 'esi4', 'esi5',
    'billing_level3', 'billing_level4', 'billing_level5',
    'shift_data',
]

def _upsert_metrics(user_id, metrics):
    flask_db.upsert_metrics(user_id, metrics)

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

@app.route('/export')
@login_required
def export_dashboard():
    rows = flask_db.get_metrics(current_user.id)
    if not rows:
        flash('No data to export.', 'error')
        return redirect(url_for('dashboard'))

    month_labels = [f"{MONTH_NAMES[r['month']]} {r['year']}" for r in rows]
    month_list = [{'month': r['month'], 'year': r['year'], 'label': lbl}
                  for r, lbl in zip(rows, month_labels)]

    sel_month = request.args.get('month', type=int)
    sel_year = request.args.get('year', type=int)
    sel_idx = len(rows) - 1
    if sel_month and sel_year:
        for i, r in enumerate(rows):
            if r['month'] == sel_month and r['year'] == sel_year:
                sel_idx = i
                break

    selected = dict(rows[sel_idx])
    selected.setdefault('patients_peers', None)
    selected.setdefault('patients_pctile', None)
    selected['month_label'] = f"{MONTH_NAMES[selected['month']]} {selected['year']}"

    metrics_json = _build_metrics_json(rows)

    # Pre-fetch all cached insights
    insight_rows = flask_db.get_all_insights(current_user.id)
    insights_data = {}
    for r in insight_rows:
        key = f"{r['chart_key']}_{r['month']}_{r['year']}"
        insights_data[key] = json.loads(r['insight_text'])

    # Pre-fetch all notes
    notes_raw = flask_db.get_all_notes(current_user.id)
    notes_data = {}
    for key, r in notes_raw.items():
        notes_data[key] = {'text': r['note_text'], 'month': r['month'], 'year': r['year'], 'chart_key': r['chart_key']}

    html = render_template(
        'export.html',
        metrics_json=metrics_json,
        month_labels=month_labels,
        month_list=month_list,
        sel_idx=sel_idx,
        selected=selected,
        username=current_user.username,
        insights_data=insights_data,
        notes_data=notes_data,
        export_date=datetime.now().strftime('%B %d, %Y'),
    )
    filename = f"ed-metrics-{selected['month_label'].replace(' ', '-')}.html"
    return Response(
        html,
        mimetype='text/html',
        headers={'Content-Disposition': f'attachment; filename="{filename}"'}
    )


@app.route('/api/months/<int:month>/<int:year>', methods=['DELETE'])
@login_required
def delete_month(month, year):
    if not flask_db.delete_month(current_user.id, month, year):
        return jsonify({'error': 'Not found'}), 404
    return jsonify({'ok': True})


@app.route('/api/notes', methods=['GET'])
@login_required
def get_all_notes():
    notes_raw = flask_db.get_all_notes(current_user.id)
    notes = {}
    for key, r in notes_raw.items():
        notes[key] = {
            'month': r['month'], 'year': r['year'], 'chart_key': r['chart_key'],
            'text': r['note_text'], 'updated_at': r.get('updated_at'),
        }
    return jsonify(notes)


@app.route('/api/notes/<chart_key>/<int:month>/<int:year>', methods=['POST'])
@login_required
def save_note(chart_key, month, year):
    text = (request.json or {}).get('text', '').strip()
    if not text:
        return jsonify({'error': 'Note text is required'}), 400
    flask_db.upsert_note(current_user.id, month, year, chart_key, text)
    return jsonify({'ok': True})


@app.route('/api/notes/<chart_key>/<int:month>/<int:year>', methods=['DELETE'])
@login_required
def delete_note(chart_key, month, year):
    flask_db.delete_note(current_user.id, month, year, chart_key)
    return jsonify({'ok': True})


if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5001))
    app.run(debug=True, port=port)
