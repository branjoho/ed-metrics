# Streamlit Migration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the Flask app with a Streamlit multi-page app backed by Supabase Postgres, deployable to Streamlit Cloud at a public URL.

**Architecture:** Streamlit multi-page app (`streamlit_app.py` = login gate, `pages/1_Dashboard.py`, `pages/2_Upload.py`) reads/writes to Supabase Postgres. `parse_pdf.py` is unchanged. AI insights logic is extracted from `app.py` into `insights.py`. `db.py` wraps all Supabase queries.

**Tech Stack:** Python, Streamlit, Supabase (supabase-py), Plotly, bcrypt, Anthropic SDK, pdfplumber

---

## File Map

| File | Action | Purpose |
|------|--------|---------|
| `streamlit_app.py` | Create | Login gate — username/password form, session state |
| `pages/1_Dashboard.py` | Create | KPI cards, Plotly charts, AI insights, notes |
| `pages/2_Upload.py` | Create | PDF upload, parse preview, save to Supabase |
| `db.py` | Create | All Supabase query functions |
| `insights.py` | Create | CHART_CONTEXTS, prompt builders, get_or_generate_insight() |
| `requirements.txt` | Modify | Add streamlit, supabase, plotly, bcrypt |
| `.streamlit/secrets.toml` | Create | Local dev secrets (gitignored) |
| `.streamlit/config.toml` | Create | Streamlit app config |
| `docs/supabase_schema.sql` | Create | SQL to run in Supabase dashboard |
| `tests/test_insights.py` | Create | Tests for prompt builder functions |
| `app.py` | Keep | Not deleted yet — reference during migration |

---

## Task 1: Update requirements and create config files

**Files:**
- Modify: `requirements.txt`
- Create: `.streamlit/secrets.toml`
- Create: `.streamlit/config.toml`
- Create: `.gitignore` (or append to existing)

- [ ] **Step 1: Update requirements.txt**

Replace entire contents with:

```
# web framework
streamlit>=1.35

# database
supabase>=2.4

# charts
plotly>=5.20

# auth
bcrypt>=4.1

# PDF parsing
pdfplumber>=0.11

# AI
anthropic>=0.25

# env
python-dotenv>=1.0

# tests
pytest>=8.0
```

- [ ] **Step 2: Create .streamlit/secrets.toml**

```bash
mkdir -p /path/to/ed-metrics/.streamlit
```

Create `.streamlit/secrets.toml`:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-key"
ANTHROPIC_API_KEY = "your-anthropic-key"
```

- [ ] **Step 3: Create .streamlit/config.toml**

```toml
[server]
headless = true

[theme]
primaryColor = "#2563eb"
backgroundColor = "#f8fafc"
secondaryBackgroundColor = "#ffffff"
textColor = "#1e293b"
```

- [ ] **Step 4: Add .streamlit/secrets.toml to .gitignore**

Append to `.gitignore` (create if it doesn't exist):

```
.streamlit/secrets.toml
__pycache__/
*.pyc
instance/
.env
```

- [ ] **Step 5: Install dependencies**

```bash
cd /path/to/ed-metrics
pip install -r requirements.txt
```

Expected: all packages install without error.

- [ ] **Step 6: Commit**

```bash
git add requirements.txt .streamlit/config.toml .gitignore
git commit -m "chore: add streamlit dependencies and config"
```

---

## Task 2: Create Supabase schema

**Files:**
- Create: `docs/supabase_schema.sql`

- [ ] **Step 1: Create docs/supabase_schema.sql**

```sql
-- Run this in the Supabase SQL Editor (supabase.com → your project → SQL Editor)

CREATE TABLE IF NOT EXISTS users (
    id SERIAL PRIMARY KEY,
    username TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS monthly_metrics (
    id SERIAL PRIMARY KEY,
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

CREATE TABLE IF NOT EXISTS chart_notes (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    chart_key TEXT NOT NULL,
    note_text TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    UNIQUE(user_id, month, year, chart_key)
);

CREATE TABLE IF NOT EXISTS insights_cache (
    id SERIAL PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id),
    month INTEGER NOT NULL,
    year INTEGER NOT NULL,
    chart_key TEXT NOT NULL,
    insight_text TEXT NOT NULL,
    generated_at TEXT NOT NULL,
    UNIQUE(user_id, month, year, chart_key)
);
```

- [ ] **Step 2: Run the schema in Supabase**

1. Go to [supabase.com](https://supabase.com) and open your project (create one if needed — free tier works)
2. Click **SQL Editor** in the left sidebar
3. Paste the contents of `docs/supabase_schema.sql` and click **Run**
4. Verify all 4 tables appear in **Table Editor**

- [ ] **Step 3: Copy Supabase credentials into .streamlit/secrets.toml**

From Supabase dashboard → **Project Settings** → **API**:
- Copy **Project URL** → `SUPABASE_URL`
- Copy **anon/public key** → `SUPABASE_KEY`

- [ ] **Step 4: Commit schema file**

```bash
git add docs/supabase_schema.sql
git commit -m "feat: add supabase postgres schema"
```

---

## Task 3: Create db.py

**Files:**
- Create: `db.py`

- [ ] **Step 1: Create db.py**

```python
import json
from datetime import datetime, timezone, timedelta
import streamlit as st
from supabase import create_client, Client


def get_client() -> Client:
    """Return a Supabase client using credentials from st.secrets."""
    return create_client(st.secrets["SUPABASE_URL"], st.secrets["SUPABASE_KEY"])


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(username: str) -> dict | None:
    """Return the user row for username, or None."""
    sb = get_client()
    res = sb.table("users").select("*").eq("username", username).execute()
    return res.data[0] if res.data else None


def create_user(username: str, password_hash: str) -> dict:
    """Insert a new user and return the created row."""
    sb = get_client()
    now = datetime.now(timezone.utc).isoformat()
    res = sb.table("users").insert({
        "username": username,
        "password_hash": password_hash,
        "created_at": now,
    }).execute()
    return res.data[0]


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

METRIC_FIELDS = [
    "patients",
    "discharge_los_me", "discharge_los_peers", "discharge_los_pctile",
    "admit_los_me", "admit_los_peers", "admit_los_pctile",
    "admission_rate_me", "admission_rate_peers", "admission_rate_pctile",
    "bed_request_me", "bed_request_peers", "bed_request_pctile",
    "returns72_me", "returns72_peers", "returns72_pctile",
    "readmits72_me", "readmits72_peers", "readmits72_pctile",
    "rad_orders_me", "rad_orders_peers", "rad_orders_pctile",
    "lab_orders_me", "lab_orders_peers", "lab_orders_pctile",
    "pts_per_hour_me", "pts_per_hour_peers", "pts_per_hour_pctile",
    "discharge_rate_me", "discharge_rate_peers", "discharge_rate_pctile",
    "icu_rate_me", "icu_rate_peers", "icu_rate_pctile",
    "rad_admit_me", "rad_admit_peers",
    "rad_disc_me", "rad_disc_peers",
    "esi1", "esi2", "esi3", "esi4", "esi5",
    "billing_level3", "billing_level4", "billing_level5",
]


def get_metrics(user_id: int) -> list[dict]:
    """Return all monthly_metrics rows for user_id, sorted by year then month."""
    sb = get_client()
    res = (
        sb.table("monthly_metrics")
        .select("*")
        .eq("user_id", user_id)
        .order("year")
        .order("month")
        .execute()
    )
    return res.data or []


def upsert_metrics(user_id: int, parsed: dict) -> None:
    """Insert or update a monthly_metrics row. Clears insights cache for that month."""
    sb = get_client()
    row = {"user_id": user_id, "month": parsed["month"], "year": parsed["year"]}
    for f in METRIC_FIELDS:
        row[f] = parsed.get(f)

    sb.table("monthly_metrics").upsert(row, on_conflict="user_id,month,year").execute()

    # Invalidate cached insights for this month
    sb.table("insights_cache").delete().eq("user_id", user_id).eq(
        "month", parsed["month"]
    ).eq("year", parsed["year"]).execute()


def delete_month(user_id: int, month: int, year: int) -> None:
    """Delete a month's metrics and its cached insights."""
    sb = get_client()
    sb.table("insights_cache").delete().eq("user_id", user_id).eq("month", month).eq(
        "year", year
    ).execute()
    sb.table("monthly_metrics").delete().eq("user_id", user_id).eq("month", month).eq(
        "year", year
    ).execute()


# ---------------------------------------------------------------------------
# Chart notes
# ---------------------------------------------------------------------------

def get_all_notes(user_id: int) -> dict:
    """Return all chart notes as {chart_key_month_year: {text, month, year, chart_key}}."""
    sb = get_client()
    res = sb.table("chart_notes").select("*").eq("user_id", user_id).execute()
    notes = {}
    for r in res.data or []:
        key = f"{r['chart_key']}_{r['month']}_{r['year']}"
        notes[key] = r
    return notes


def upsert_note(user_id: int, month: int, year: int, chart_key: str, text: str) -> None:
    """Insert or update a chart note."""
    sb = get_client()
    now = datetime.now(timezone.utc).isoformat()
    sb.table("chart_notes").upsert(
        {
            "user_id": user_id,
            "month": month,
            "year": year,
            "chart_key": chart_key,
            "note_text": text,
            "created_at": now,
            "updated_at": now,
        },
        on_conflict="user_id,month,year,chart_key",
    ).execute()


def delete_note(user_id: int, month: int, year: int, chart_key: str) -> None:
    sb = get_client()
    sb.table("chart_notes").delete().eq("user_id", user_id).eq("month", month).eq(
        "year", year
    ).eq("chart_key", chart_key).execute()


# ---------------------------------------------------------------------------
# Insights cache
# ---------------------------------------------------------------------------

def get_cached_insight(user_id: int, month: int, year: int, chart_key: str) -> list | None:
    """Return cached insights if they exist and are less than 90 days old."""
    sb = get_client()
    res = (
        sb.table("insights_cache")
        .select("insight_text, generated_at")
        .eq("user_id", user_id)
        .eq("month", month)
        .eq("year", year)
        .eq("chart_key", chart_key)
        .execute()
    )
    if not res.data:
        return None
    row = res.data[0]
    generated_at = datetime.fromisoformat(row["generated_at"])
    if datetime.now(timezone.utc) - generated_at < timedelta(days=90):
        return json.loads(row["insight_text"])
    return None


def save_insight_cache(
    user_id: int, month: int, year: int, chart_key: str, insights: list
) -> None:
    sb = get_client()
    sb.table("insights_cache").upsert(
        {
            "user_id": user_id,
            "month": month,
            "year": year,
            "chart_key": chart_key,
            "insight_text": json.dumps(insights),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        },
        on_conflict="user_id,month,year,chart_key",
    ).execute()
```

- [ ] **Step 2: Verify db.py is importable**

```bash
cd /path/to/ed-metrics
python -c "import db; print('db.py OK')"
```

Expected: `db.py OK` (will fail if supabase package missing — run `pip install -r requirements.txt` first)

- [ ] **Step 3: Commit**

```bash
git add db.py
git commit -m "feat: add db.py supabase query wrapper"
```

---

## Task 4: Create insights.py

**Files:**
- Create: `insights.py`
- Create: `tests/test_insights.py`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_insights.py`:

```python
import pytest
from insights import _build_insights_prompt, _build_overview_prompt, CHART_CONTEXTS


SAMPLE_ROW = {
    "month": 9, "year": 2025, "patients": 125,
    "discharge_los_me": 3.47, "discharge_los_peers": 3.8, "discharge_los_pctile": 13,
    "admit_los_me": 5.1, "admit_los_peers": 5.5, "admit_los_pctile": 30,
    "admission_rate_me": 11.2, "admission_rate_peers": 17.6, "admission_rate_pctile": 15,
    "bed_request_me": 143, "bed_request_peers": 171, "bed_request_pctile": 28,
    "returns72_me": 2.1, "returns72_peers": 2.5, "returns72_pctile": 35,
    "readmits72_me": 0.8, "readmits72_peers": 1.2, "readmits72_pctile": 25,
    "rad_orders_me": 31, "rad_orders_peers": 35, "rad_orders_pctile": 40,
    "lab_orders_me": 70, "lab_orders_peers": 72, "lab_orders_pctile": 45,
    "pts_per_hour_me": 1.8, "pts_per_hour_peers": 1.6, "pts_per_hour_pctile": 70,
    "discharge_rate_me": 88.8, "discharge_rate_peers": 82.4, "discharge_rate_pctile": 75,
    "icu_rate_me": 5.0, "icu_rate_peers": 6.0, "icu_rate_pctile": 40,
    "rad_admit_me": 61, "rad_admit_peers": 49,
    "rad_disc_me": 22, "rad_disc_peers": 30,
    "esi1": 0.8, "esi2": 20.0, "esi3": 49.6, "esi4": 23.2, "esi5": 6.4,
    "billing_level3": 5, "billing_level4": 57, "billing_level5": 38,
}


def test_chart_contexts_keys():
    expected_keys = {
        "dischargeLOS", "admitLOS", "admissionRate", "bedRequest",
        "returns72", "readmits72", "icuRate", "radOrders", "labOrders",
        "ptsPerHour", "dischargeRate", "volume", "radByDispo", "esiChart",
        "pctTable", "overview",
    }
    assert expected_keys == set(CHART_CONTEXTS.keys())


def test_build_insights_prompt_returns_string():
    prompt = _build_insights_prompt("dischargeLOS", SAMPLE_ROW, [SAMPLE_ROW])
    assert isinstance(prompt, str)
    assert "Discharge" in prompt
    assert "3.47" in prompt


def test_build_insights_prompt_unknown_key_returns_none():
    result = _build_insights_prompt("nonexistent", SAMPLE_ROW, [SAMPLE_ROW])
    assert result is None


def test_build_overview_prompt_returns_string():
    prompt = _build_overview_prompt(SAMPLE_ROW, [SAMPLE_ROW])
    assert isinstance(prompt, str)
    assert "Sep 2025" in prompt
    assert "3.47" in prompt


def test_build_insights_prompt_overview_delegates():
    prompt = _build_insights_prompt("overview", SAMPLE_ROW, [SAMPLE_ROW])
    assert prompt is not None
    assert "Sep 2025" in prompt
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /path/to/ed-metrics
pytest tests/test_insights.py -v
```

Expected: `ModuleNotFoundError: No module named 'insights'`

- [ ] **Step 3: Create insights.py**

```python
import json
import anthropic
import streamlit as st
from datetime import datetime, timezone, timedelta

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
    'radByDispo':    ('Radiology by Disposition', 'rad_admit_me', 'rad_admit_peers', None, 'Radiology ordering split by admitted vs discharged patients.'),
    'esiChart':      ('ESI Acuity Mix', 'esi3', None, None, 'Distribution across ESI levels: 1=critical, 2=emergent, 3=urgent, 4=semi-urgent, 5=non-urgent.'),
    'pctTable':      ('Overall Percentile Rankings', 'discharge_los_pctile', None, None, 'Summary of all metric percentile rankings.'),
    'overview':      ('Overall Performance Summary', 'discharge_los_pctile', None, None, 'High-level snapshot of this month\'s performance across all key metrics relative to peers.'),
}


def _build_overview_prompt(sel_row: dict, all_rows: list[dict]) -> str:
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


def _build_insights_prompt(chart_key: str, sel_row: dict, all_rows: list[dict]) -> str | None:
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


def get_or_generate_insight(
    user_id: int,
    month: int,
    year: int,
    chart_key: str,
    sel_row: dict,
    all_rows: list[dict],
) -> list[dict] | None:
    """
    Return insights for a chart. Checks cache first (via db), calls Claude if miss.
    Returns None if Anthropic API key is not configured.
    """
    import db

    # Check cache
    cached = db.get_cached_insight(user_id, month, year, chart_key)
    if cached is not None:
        return cached

    # Build prompt
    prompt = _build_insights_prompt(chart_key, sel_row, all_rows)
    if not prompt:
        return None

    # Call Claude
    api_key = st.secrets.get("ANTHROPIC_API_KEY")
    if not api_key:
        return None

    client = anthropic.Anthropic(api_key=api_key)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=1024,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    raw = message.content[0].text.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    insights = json.loads(raw)

    # Cache result
    db.save_insight_cache(user_id, month, year, chart_key, insights)
    return insights
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
pytest tests/test_insights.py -v
```

Expected: 5 tests pass.

- [ ] **Step 5: Commit**

```bash
git add insights.py tests/test_insights.py
git commit -m "feat: extract insights logic to insights.py with tests"
```

---

## Task 5: Create streamlit_app.py (login gate)

**Files:**
- Create: `streamlit_app.py`

- [ ] **Step 1: Create streamlit_app.py**

```python
import re
import bcrypt
import streamlit as st
import db

st.set_page_config(page_title="ED Metrics", page_icon="🏥", layout="wide")


def _check_login(username: str, password: str) -> dict | None:
    """Return user dict if credentials valid, else None."""
    user = db.get_user(username)
    if not user:
        return None
    if bcrypt.checkpw(password.encode(), user["password_hash"].encode()):
        return user
    return None


def _register(username: str, password: str) -> str | None:
    """
    Create a new user. Returns error string if validation fails or username taken,
    else None on success.
    """
    if not re.match(r'^[a-zA-Z0-9_]{3,32}$', username):
        return "Username must be 3–32 characters (letters, numbers, underscores only)."
    if len(password) < 8:
        return "Password must be at least 8 characters."
    if db.get_user(username):
        return "Username already taken."
    pw_hash = bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()
    db.create_user(username, pw_hash)
    return None


# ── Session state bootstrap ──────────────────────────────────────────────────
if "user_id" not in st.session_state:
    st.session_state.user_id = None
    st.session_state.username = None

# ── Already logged in — show welcome and nav hint ────────────────────────────
if st.session_state.user_id:
    st.title("ED Metrics")
    st.success(f"Logged in as **{st.session_state.username}**")
    st.info("Use the sidebar to navigate to **Dashboard** or **Upload**.")
    if st.button("Log out"):
        st.session_state.user_id = None
        st.session_state.username = None
        st.rerun()
    st.stop()

# ── Login / Register tabs ────────────────────────────────────────────────────
st.title("ED Metrics")
tab_login, tab_register = st.tabs(["Log in", "Register"])

with tab_login:
    with st.form("login_form"):
        username = st.text_input("Username")
        password = st.text_input("Password", type="password")
        submitted = st.form_submit_button("Log in")
    if submitted:
        user = _check_login(username.strip(), password)
        if user:
            st.session_state.user_id = user["id"]
            st.session_state.username = user["username"]
            st.rerun()
        else:
            st.error("Invalid username or password.")

with tab_register:
    with st.form("register_form"):
        new_username = st.text_input("Username")
        new_password = st.text_input("Password", type="password")
        submitted_reg = st.form_submit_button("Create account")
    if submitted_reg:
        err = _register(new_username.strip(), new_password)
        if err:
            st.error(err)
        else:
            st.success("Account created. Please log in.")
```

- [ ] **Step 2: Run the app locally to verify login works**

```bash
cd /path/to/ed-metrics
streamlit run streamlit_app.py
```

Open the URL shown in the terminal (usually `http://localhost:8501`).
- Register a test account
- Log in with that account
- Verify you see "Logged in as username" and the logout button works

- [ ] **Step 3: Commit**

```bash
git add streamlit_app.py
git commit -m "feat: add streamlit login gate"
```

---

## Task 6: Create pages/2_Upload.py

**Files:**
- Create: `pages/2_Upload.py`

- [ ] **Step 1: Create pages/ directory and 2_Upload.py**

```bash
mkdir -p /path/to/ed-metrics/pages
```

Create `pages/2_Upload.py`:

```python
import os
import tempfile
import streamlit as st
import db
from parse_pdf import parse_metrics, ParseError

st.set_page_config(page_title="Upload — ED Metrics", page_icon="📤", layout="wide")

MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

# Auth guard
if not st.session_state.get("user_id"):
    st.warning("Please log in first.")
    st.stop()

user_id = st.session_state.user_id

st.title("Upload Monthly Report")
st.write("Upload one or more ED Provider Metrics PDFs. Duplicate months are replaced.")

uploaded_files = st.file_uploader(
    "Choose PDF file(s)",
    type=["pdf"],
    accept_multiple_files=True,
)

if uploaded_files:
    results = []
    for uploaded_file in uploaded_files:
        # Write to temp file so pdfplumber can open it
        with tempfile.NamedTemporaryFile(suffix=f"_{uploaded_file.name}", delete=False) as tmp:
            tmp.write(uploaded_file.read())
            tmp_path = tmp.name

        try:
            metrics = parse_metrics(tmp_path)
        except ParseError as e:
            results.append({"name": uploaded_file.name, "ok": False, "error": str(e)})
            continue
        except Exception as e:
            results.append({"name": uploaded_file.name, "ok": False,
                            "error": "PDF appears password-protected or corrupted."})
            continue
        finally:
            try:
                os.unlink(tmp_path)
            except OSError:
                pass

        if not metrics.get("month") or not metrics.get("year"):
            results.append({
                "name": uploaded_file.name, "ok": False,
                "error": "Could not determine month/year. Rename file to MM_YYYY format.",
            })
            continue

        results.append({
            "name": uploaded_file.name,
            "ok": True,
            "metrics": metrics,
            "label": f"{MONTH_NAMES[metrics['month']]} {metrics['year']}",
        })

    # Show preview
    errors = [r for r in results if not r["ok"]]
    successes = [r for r in results if r["ok"]]

    if errors:
        for e in errors:
            st.error(f"**{e['name']}**: {e['error']}")

    if successes:
        st.subheader("Ready to save")
        for s in successes:
            m = s["metrics"]
            st.write(f"**{s['label']}** — {m.get('patients')} patients, "
                     f"discharge LOS {m.get('discharge_los_me')}h, "
                     f"readmit rate {m.get('readmits72_me')}%")

        if st.button("Save to dashboard", type="primary"):
            for s in successes:
                db.upsert_metrics(user_id, s["metrics"])
            st.success(f"Saved {len(successes)} month(s). Go to Dashboard to view.")
```

- [ ] **Step 2: Test upload page manually**

```bash
streamlit run streamlit_app.py
```

1. Log in
2. Click **2_Upload** in the sidebar
3. Upload a real PDF — verify the preview shows correct month/patients/readmit
4. Click **Save to dashboard** — verify no errors

- [ ] **Step 3: Commit**

```bash
git add pages/2_Upload.py
git commit -m "feat: add upload page with PDF parse preview"
```

---

## Task 7: Create pages/1_Dashboard.py

**Files:**
- Create: `pages/1_Dashboard.py`

This is the largest task. Build it in sections within the same file.

- [ ] **Step 1: Create pages/1_Dashboard.py with structure and helpers**

```python
import streamlit as st
import plotly.graph_objects as go
import db
import insights as ins

st.set_page_config(page_title="Dashboard — ED Metrics", page_icon="📊", layout="wide")

MONTH_NAMES = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun',
               'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec']

SEVERITY_COLOR = {
    "alert": "#dc2626",
    "warn":  "#d97706",
    "good":  "#16a34a",
    "neutral": "#64748b",
}

# Auth guard
if not st.session_state.get("user_id"):
    st.warning("Please log in first.")
    st.stop()

user_id = st.session_state.user_id
rows = db.get_metrics(user_id)

if not rows:
    st.title("Dashboard")
    st.info("No data yet. Go to **Upload** to add your first monthly report.")
    st.stop()

# ── Month selector ───────────────────────────────────────────────────────────
month_labels = [f"{MONTH_NAMES[r['month']]} {r['year']}" for r in rows]
sel_label = st.selectbox("Month", month_labels, index=len(month_labels) - 1)
sel_idx = month_labels.index(sel_label)
sel = rows[sel_idx]

st.title(f"ED Metrics — {sel_label}")
st.caption(f"Logged in as {st.session_state.username}")


# ── Helpers ──────────────────────────────────────────────────────────────────

def _v(row, field):
    """Return field value or '—' for display."""
    val = row.get(field)
    return val if val is not None else None


def _pctile_color(pctile, higher_is_better=False):
    """Return a CSS color string based on percentile. Lower = better by default."""
    if pctile is None:
        return "#64748b"
    if higher_is_better:
        pctile = 100 - pctile
    if pctile <= 33:
        return "#16a34a"   # green — good
    if pctile <= 60:
        return "#d97706"   # yellow — ok
    return "#dc2626"       # red — concern


def make_line_chart(labels, me_vals, peer_vals, title, sel_idx, y_label=""):
    """Return a Plotly figure with me vs peers lines and a marker on the selected month."""
    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=labels, y=me_vals, name="You",
        line=dict(color="#2563eb", width=2.5),
        mode="lines+markers",
    ))
    if peer_vals and any(v is not None for v in peer_vals):
        fig.add_trace(go.Scatter(
            x=labels, y=peer_vals, name="Peers",
            line=dict(color="#94a3b8", width=1.5, dash="dot"),
            mode="lines+markers",
        ))
    # Highlight selected month
    if me_vals[sel_idx] is not None:
        fig.add_trace(go.Scatter(
            x=[labels[sel_idx]], y=[me_vals[sel_idx]],
            mode="markers",
            marker=dict(color="#2563eb", size=12, symbol="circle"),
            showlegend=False,
        ))
    fig.update_layout(
        title=title, height=280, margin=dict(t=40, b=20, l=0, r=0),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        yaxis_title=y_label,
        plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="#e2e8f0")
    return fig


def _col(field):
    return [r.get(field) for r in rows]


def render_insight_panel(chart_key, sel, rows):
    """Render AI insights expander for a chart."""
    with st.expander("AI Insights"):
        with st.spinner("Loading insights..."):
            try:
                result = ins.get_or_generate_insight(
                    user_id, sel["month"], sel["year"], chart_key, sel, rows
                )
            except Exception as e:
                st.error(f"Could not load insights: {e}")
                return
        if result is None:
            st.caption("Insights unavailable — ANTHROPIC_API_KEY not configured.")
            return
        for item in result:
            color = SEVERITY_COLOR.get(item.get("severity", "neutral"), "#64748b")
            st.markdown(
                f'<div style="border-left: 4px solid {color}; padding: 8px 12px; '
                f'margin-bottom: 8px; background: #f8fafc; border-radius: 4px;">'
                f'{item["text"]}</div>',
                unsafe_allow_html=True,
            )


def render_note_widget(chart_key, sel):
    """Render save/delete note widget for a chart."""
    note_key = f"{chart_key}_{sel['month']}_{sel['year']}"
    all_notes = db.get_all_notes(user_id)
    existing = all_notes.get(note_key, {}).get("note_text", "")

    with st.expander("My Note"):
        note_text = st.text_area("Note", value=existing, key=f"note_{note_key}",
                                 label_visibility="collapsed")
        col1, col2 = st.columns([1, 1])
        with col1:
            if st.button("Save", key=f"save_{note_key}") and note_text.strip():
                db.upsert_note(user_id, sel["month"], sel["year"], chart_key,
                               note_text.strip())
                st.success("Saved.")
        with col2:
            if existing and st.button("Delete", key=f"del_{note_key}"):
                db.delete_note(user_id, sel["month"], sel["year"], chart_key)
                st.rerun()
```

- [ ] **Step 2: Add KPI cards section**

Append to `pages/1_Dashboard.py`:

```python
# ── KPI Cards ────────────────────────────────────────────────────────────────
st.subheader("Key Metrics — " + sel_label)

kpi_metrics = [
    ("Patients", "patients", None, False),
    ("Discharge LOS (h)", "discharge_los_me", "discharge_los_pctile", False),
    ("Admit LOS (h)", "admit_los_me", "admit_los_pctile", False),
    ("Admission Rate (%)", "admission_rate_me", "admission_rate_pctile", False),
    ("Bed Request (min)", "bed_request_me", "bed_request_pctile", False),
    ("72h Returns (%)", "returns72_me", "returns72_pctile", False),
    ("72h Readmits (%)", "readmits72_me", "readmits72_pctile", False),
    ("Pts/Hour", "pts_per_hour_me", "pts_per_hour_pctile", True),
    ("Discharge Rate (%)", "discharge_rate_me", "discharge_rate_pctile", True),
    ("ICU Rate (%)", "icu_rate_me", "icu_rate_pctile", False),
]

cols = st.columns(5)
for i, (label, val_field, pctile_field, higher_better) in enumerate(kpi_metrics):
    val = _v(sel, val_field)
    pctile = _v(sel, pctile_field) if pctile_field else None
    color = _pctile_color(pctile, higher_is_better=higher_better) if pctile else "#64748b"
    with cols[i % 5]:
        display_val = f"{val}" if val is not None else "—"
        pctile_str = f"P{int(pctile)}" if pctile is not None else ""
        st.markdown(
            f'<div style="background:#fff;border:1px solid #e2e8f0;border-radius:10px;'
            f'padding:14px 16px;border-top:4px solid {color};">'
            f'<div style="font-size:12px;color:#64748b;margin-bottom:4px;">{label}</div>'
            f'<div style="font-size:22px;font-weight:700;color:#1e293b;">{display_val}</div>'
            f'<div style="font-size:12px;color:{color};font-weight:600;">{pctile_str}</div>'
            f'</div>',
            unsafe_allow_html=True,
        )
```

- [ ] **Step 3: Add line charts for time/rate metrics**

Append to `pages/1_Dashboard.py`:

```python
# ── Line Charts ───────────────────────────────────────────────────────────────
st.markdown("---")
st.subheader("Trends Over Time")

LINE_CHARTS = [
    ("Discharge LOS (Hours)", "discharge_los_me", "discharge_los_peers", "dischargeLOS"),
    ("Admit LOS (Hours)", "admit_los_me", "admit_los_peers", "admitLOS"),
    ("Admission Rate (%)", "admission_rate_me", "admission_rate_peers", "admissionRate"),
    ("Time to Bed Request (min)", "bed_request_me", "bed_request_peers", "bedRequest"),
    ("72-Hour Return Rate (%)", "returns72_me", "returns72_peers", "returns72"),
    ("72-Hour Readmit Rate (%)", "readmits72_me", "readmits72_peers", "readmits72"),
    ("Radiology Orders (%)", "rad_orders_me", "rad_orders_peers", "radOrders"),
    ("Lab Orders (%)", "lab_orders_me", "lab_orders_peers", "labOrders"),
    ("Patients Per Hour", "pts_per_hour_me", "pts_per_hour_peers", "ptsPerHour"),
    ("Discharge Rate (%)", "discharge_rate_me", "discharge_rate_peers", "dischargeRate"),
    ("ICU Admission Rate (%)", "icu_rate_me", "icu_rate_peers", "icuRate"),
]

for title, me_field, peer_field, chart_key in LINE_CHARTS:
    st.markdown(f"#### {title}")
    fig = make_line_chart(
        month_labels, _col(me_field), _col(peer_field), title, sel_idx
    )
    st.plotly_chart(fig, use_container_width=True)
    render_insight_panel(chart_key, sel, rows)
    render_note_widget(chart_key, sel)
    st.markdown("---")
```

- [ ] **Step 4: Add volume, radByDispo, ESI, and percentile table sections**

Append to `pages/1_Dashboard.py`:

```python
# ── Volume bar chart ─────────────────────────────────────────────────────────
st.subheader("Monthly Patient Volume")
vol_fig = go.Figure(go.Bar(
    x=month_labels, y=_col("patients"),
    marker_color="#2563eb",
))
vol_fig.update_layout(height=250, margin=dict(t=20, b=20, l=0, r=0),
                      plot_bgcolor="#ffffff", paper_bgcolor="#ffffff")
vol_fig.update_xaxes(showgrid=False)
vol_fig.update_yaxes(gridcolor="#e2e8f0")
st.plotly_chart(vol_fig, use_container_width=True)
render_insight_panel("volume", sel, rows)
render_note_widget("volume", sel)

st.markdown("---")

# ── Radiology by disposition ──────────────────────────────────────────────────
st.subheader("Radiology by Disposition")
rad_fig = go.Figure()
rad_fig.add_trace(go.Bar(name="Admit — You",  x=month_labels, y=_col("rad_admit_me"),
                         marker_color="#2563eb"))
rad_fig.add_trace(go.Bar(name="Admit — Peers", x=month_labels, y=_col("rad_admit_peers"),
                         marker_color="#93c5fd"))
rad_fig.add_trace(go.Bar(name="Discharge — You",  x=month_labels, y=_col("rad_disc_me"),
                         marker_color="#7c3aed"))
rad_fig.add_trace(go.Bar(name="Discharge — Peers", x=month_labels, y=_col("rad_disc_peers"),
                         marker_color="#c4b5fd"))
rad_fig.update_layout(barmode="group", height=280,
                      margin=dict(t=20, b=20, l=0, r=0),
                      plot_bgcolor="#ffffff", paper_bgcolor="#ffffff",
                      legend=dict(orientation="h", yanchor="bottom", y=1.02))
rad_fig.update_xaxes(showgrid=False)
rad_fig.update_yaxes(gridcolor="#e2e8f0", title="% with Radiology Orders")
st.plotly_chart(rad_fig, use_container_width=True)
render_insight_panel("radByDispo", sel, rows)
render_note_widget("radByDispo", sel)

st.markdown("---")

# ── ESI distribution ──────────────────────────────────────────────────────────
st.subheader("ESI Acuity Mix — " + sel_label)
esi_labels = ["ESI 1 (Critical)", "ESI 2 (Emergent)", "ESI 3 (Urgent)",
              "ESI 4 (Semi-urgent)", "ESI 5 (Non-urgent)"]
esi_vals = [
    _v(sel, "esi1"), _v(sel, "esi2"), _v(sel, "esi3"),
    _v(sel, "esi4"), _v(sel, "esi5"),
]
if any(v is not None for v in esi_vals):
    esi_fig = go.Figure(go.Bar(
        x=esi_labels, y=esi_vals,
        marker_color=["#dc2626", "#d97706", "#2563eb", "#16a34a", "#64748b"],
    ))
    esi_fig.update_layout(height=250, margin=dict(t=20, b=20, l=0, r=0),
                          yaxis_title="%", plot_bgcolor="#ffffff",
                          paper_bgcolor="#ffffff")
    esi_fig.update_xaxes(showgrid=False)
    esi_fig.update_yaxes(gridcolor="#e2e8f0")
    st.plotly_chart(esi_fig, use_container_width=True)
else:
    st.caption("ESI data not available for this month.")
render_insight_panel("esiChart", sel, rows)
render_note_widget("esiChart", sel)

st.markdown("---")

# ── Percentile rankings table ─────────────────────────────────────────────────
st.subheader("Percentile Rankings — " + sel_label)
st.caption("Lower percentile = better for time/rate metrics. Higher = better for productivity.")

pct_rows = [
    ("Discharge LOS",     _v(sel, "discharge_los_pctile"),     False),
    ("Admit LOS",         _v(sel, "admit_los_pctile"),          False),
    ("Admission Rate",    _v(sel, "admission_rate_pctile"),     False),
    ("Time to Bed Req",   _v(sel, "bed_request_pctile"),        False),
    ("72h Returns",       _v(sel, "returns72_pctile"),          False),
    ("72h Readmits",      _v(sel, "readmits72_pctile"),         False),
    ("Radiology Orders",  _v(sel, "rad_orders_pctile"),         False),
    ("Lab Orders",        _v(sel, "lab_orders_pctile"),         False),
    ("Patients/Hour",     _v(sel, "pts_per_hour_pctile"),       True),
    ("Discharge Rate",    _v(sel, "discharge_rate_pctile"),     True),
    ("ICU Rate",          _v(sel, "icu_rate_pctile"),           False),
]

for metric_name, pctile, higher_better in pct_rows:
    color = _pctile_color(pctile, higher_is_better=higher_better)
    pctile_str = f"P{int(pctile)}" if pctile is not None else "—"
    bar_pct = pctile if pctile is not None else 0
    st.markdown(
        f'<div style="display:flex;align-items:center;margin-bottom:6px;">'
        f'<div style="width:180px;font-size:13px;color:#1e293b;">{metric_name}</div>'
        f'<div style="flex:1;background:#e2e8f0;border-radius:4px;height:12px;overflow:hidden;">'
        f'<div style="width:{bar_pct}%;background:{color};height:100%;border-radius:4px;"></div>'
        f'</div>'
        f'<div style="width:48px;text-align:right;font-size:13px;font-weight:600;color:{color};margin-left:8px;">'
        f'{pctile_str}</div></div>',
        unsafe_allow_html=True,
    )
render_insight_panel("pctTable", sel, rows)

st.markdown("---")

# ── AI Overview ───────────────────────────────────────────────────────────────
st.subheader("Monthly Summary — " + sel_label)
render_insight_panel("overview", sel, rows)

# ── Delete month ──────────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("Danger zone"):
    st.warning(f"Delete **{sel_label}** data permanently?")
    if st.button("Delete this month", type="secondary"):
        db.delete_month(user_id, sel["month"], sel["year"])
        st.success(f"{sel_label} deleted.")
        st.rerun()
```

- [ ] **Step 5: Run app and verify dashboard end-to-end**

```bash
streamlit run streamlit_app.py
```

1. Log in
2. Go to **1_Dashboard**
3. Verify month selector works
4. Verify KPI cards show correct values for selected month
5. Verify Plotly charts render with me vs peers lines
6. Click **AI Insights** on any chart — verify insights load (requires ANTHROPIC_API_KEY in secrets.toml)
7. Verify note save/delete works
8. Verify percentile table renders with color bars

- [ ] **Step 6: Commit**

```bash
git add pages/1_Dashboard.py
git commit -m "feat: add dashboard page with KPI cards, charts, insights, notes"
```

---

## Task 8: Deploy to Streamlit Cloud

**Files:** None changed

- [ ] **Step 1: Push repo to GitHub**

```bash
git remote add origin https://github.com/your-username/ed-metrics.git   # if not already set
git push -u origin main
```

Verify `.streamlit/secrets.toml` is **not** committed (it should be in .gitignore).

- [ ] **Step 2: Create Streamlit Cloud app**

1. Go to [share.streamlit.io](https://share.streamlit.io)
2. Click **New app**
3. Select your GitHub repo and branch
4. Set **Main file path** to `streamlit_app.py`
5. Click **Advanced settings** → **Secrets** and paste:

```toml
SUPABASE_URL = "https://your-project.supabase.co"
SUPABASE_KEY = "your-anon-key"
ANTHROPIC_API_KEY = "your-anthropic-key"
```

6. Click **Deploy**

- [ ] **Step 3: Verify deployment**

1. Open the public URL Streamlit Cloud provides
2. Register a new account
3. Upload a PDF
4. Confirm dashboard renders correctly

- [ ] **Step 4: Share the URL**

The app is live. Share the URL with other physicians — they can register their own accounts and upload their own PDFs.

---

## Notes on Existing Tests

The existing tests (`tests/test_auth.py`, `tests/test_dashboard.py`, `tests/test_upload.py`, etc.) test Flask routes and will fail after migration since Flask is no longer running. They can be deleted once the Streamlit app is verified working. The new test suite is `tests/test_insights.py`.
