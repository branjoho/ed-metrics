import os
import re
import sqlite3
from datetime import datetime, timezone
from flask import Flask, g, current_app, render_template, redirect, url_for, flash, request
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
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

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html', metrics_json={}, months=[], has_data=False, month_list=[], sel_idx=0, selected=None, username=current_user.username)

@app.route('/upload')
@login_required
def upload_page():
    return render_template('upload.html')

if __name__ == '__main__':
    init_db()
    app.run(debug=True)
