# ED Provider Metrics Dashboard — Design Spec

## Overview

A Flask web application that allows ED providers at Seattle Children's Hospital to upload their monthly ED Provider Metrics PDFs and get a persistent, multi-month dashboard with LLM-generated insights. Each provider logs in, uploads PDFs, and sees their own history over time.

---

## Users & Access

- **Target users:** ED attending physicians at Seattle Children's Hospital
- **Auth:** Username + bcrypt-hashed password, Flask session cookie
- **Registration:** Self-service; no admin approval required
- **Data isolation:** Each user sees only their own data — all queries filter by `user_id`

---

## Architecture

**Stack:** Python/Flask, SQLite, Jinja2 templates, Chart.js, Anthropic Claude API

**Single-app structure:**
```
ed-metrics/
  app.py              # Flask app, routes, DB setup
  parse_pdf.py        # pdfplumber-based PDF parser
  requirements.txt
  templates/
    base.html         # nav, session handling
    login.html
    register.html
    dashboard.html    # full dashboard (Jinja2 version of ED_Provider_Dashboard.html)
    upload.html
  static/
    style.css         # shared styles
  metrics.db          # SQLite (gitignored)
```

---

## Database Schema

### `users`
| column | type | notes |
|--------|------|-------|
| id | INTEGER PK | |
| username | TEXT UNIQUE NOT NULL | |
| password_hash | TEXT NOT NULL | bcrypt |
| created_at | DATETIME | |

### `monthly_metrics`
| column | type | notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK | → users.id |
| month | INTEGER | 1–12 |
| year | INTEGER | |
| patients | INTEGER | |
| discharge_los_me | REAL | |
| discharge_los_peers | REAL | |
| discharge_los_pctile | REAL | |
| admit_los_me | REAL | |
| admit_los_peers | REAL | |
| admit_los_pctile | REAL | |
| admission_rate_me | REAL | |
| admission_rate_peers | REAL | |
| admission_rate_pctile | REAL | |
| bed_request_me | REAL | minutes |
| bed_request_peers | REAL | |
| bed_request_pctile | REAL | |
| returns72_me | REAL | % |
| returns72_peers | REAL | |
| returns72_pctile | REAL | |
| readmits72_me | REAL | % |
| readmits72_peers | REAL | |
| readmits72_pctile | REAL | |
| rad_orders_me | REAL | % |
| rad_orders_peers | REAL | |
| rad_orders_pctile | REAL | |
| lab_orders_me | REAL | % |
| lab_orders_peers | REAL | |
| lab_orders_pctile | REAL | |
| pts_per_hour_me | REAL | |
| pts_per_hour_peers | REAL | |
| pts_per_hour_pctile | REAL | |
| discharge_rate_me | REAL | % |
| discharge_rate_peers | REAL | |
| discharge_rate_pctile | REAL | |
| icu_rate_me | REAL | % |
| icu_rate_peers | REAL | |
| icu_rate_pctile | REAL | |
| rad_admit_me | REAL | % radiology on admitted pts |
| rad_admit_peers | REAL | |
| rad_disc_me | REAL | % radiology on discharged pts |
| rad_disc_peers | REAL | |
| billing_level3 | INTEGER | visit count from PDF text; nullable |
| billing_level4 | INTEGER | nullable |
| billing_level5 | INTEGER | nullable |
| esi1 | REAL | % ESI-1 |
| esi2 | REAL | |
| esi3 | REAL | |
| esi4 | REAL | |
| esi5 | REAL | |
| UNIQUE | (user_id, month, year) | upsert on re-upload |

### `insights_cache`
| column | type | notes |
|--------|------|-------|
| id | INTEGER PK | |
| user_id | INTEGER FK | |
| month | INTEGER | |
| year | INTEGER | |
| chart_key | TEXT | e.g. `dischargeLOS`, `overview` |
| insight_text | TEXT | JSON string: list of {severity, text, tags} |
| generated_at | DATETIME | |
| UNIQUE | (user_id, month, year, chart_key) | |

---

## Routes

| Method | Path | Auth | Description |
|--------|------|------|-------------|
| GET | `/` | — | Redirect to `/dashboard` if logged in, else `/login` |
| GET/POST | `/login` | — | Login form |
| GET/POST | `/register` | — | Registration form |
| POST | `/logout` | ✓ | Clear session |
| GET | `/dashboard` | ✓ | Main dashboard; `?month=2&year=2026` selects active month; month list server-rendered into template |
| GET | `/upload` | ✓ | Upload form (renders `upload.html`) |
| POST | `/upload` | ✓ | PDF upload → parse → store → redirect to dashboard |
| GET | `/api/insights/<chart_key>/<month>/<year>` | ✓ | Return cached insights or generate + cache |
| DELETE | `/api/months/<month>/<year>` | ✓ | Delete a month's data + all its `insights_cache` rows (cascade delete) |

---

## Dashboard UI

The dashboard is a Jinja2 adaptation of the existing `ED_Provider_Dashboard.html`. All hardcoded data is replaced by server-rendered JSON. The full feature set is preserved:

**5 sections:**
1. **Overview** — 12 KPI cards with value, peer avg, percentile badge, goal badge; auto performance summary
2. **Throughput** — Discharge LOS, Admit LOS, Bed Request Time, Admission Rate, Radiology by Disposition, Lab Orders
3. **Safety** — 72hr Return Rate, 72hr Readmit Rate, ICU Admission Rate
4. **Volume & Productivity** — Patients Seen, Patients/Hour, Discharge Rate, ESI Acuity Mix, Full Percentile Ranking Table
5. **Billing** — Visit complexity distribution; WRVU/charges shown as "—" if unavailable

**Additional UI features:**
- Sticky nav with section anchors
- Month selector dropdown (all uploaded months for this user)
- "Set My Goals" slide-out panel — goals saved to browser localStorage, render as dashed goal lines on charts
- Per-chart "Insights" drawer — LLM-generated, loaded on first open then cached
- Rolling 3-month average lines on safety charts
- Upload button in nav (or empty state if no months uploaded)

**Data flow:** Dashboard route queries all months for the user, passes the full history as a JSON blob to the template. JavaScript reads it exactly as in the existing HTML (`const D = {...}`), with trend data across all months.

---

## PDF Parser (`parse_pdf.py`)

```python
def parse_metrics(pdf_path: str) -> dict:
    """
    Parse an ED Provider Metrics PDF.
    Returns a dict with all metric fields, or raises ParseError.
    """
```

- Uses pdfplumber to extract text from specific pages
- Returns `None` for any field that can't be parsed (graceful partial data)
- Raises `ParseError` with a human-readable message if the file is not a recognized ED metrics PDF
- **Must be written by reading the actual PDFs** — page layout and field positions need to be determined during implementation

---

## LLM Insights

**Trigger:** User opens an Insights drawer for the first time for a given chart/month.

**API call:** `GET /api/insights/<chart_key>/<month>/<year>`

1. Check `insights_cache` — if found and < 90 days old, return cached
2. Build prompt: include the user's metrics for the selected month, their trend over all uploaded months, peer benchmarks, and chart-specific context
3. Call Claude API (`claude-sonnet-4-6`, temp 0.3)
4. Parse response into structured list of `{severity: "alert|warn|good|neutral", text: "...", tags: [...]}`
5. Store in `insights_cache`; return to client

**Prompt structure:**
```
You are analyzing ED provider performance metrics. Generate 2-4 insights for the [chart name] chart.

This month ([month/year]):
- Provider value: X
- Peer average: Y
- Percentile: Z

Trend (all months):
[table of values]

Return JSON: [{"severity": "alert|warn|good|neutral", "text": "...", "tags": ["trend|bench|pos|safety"]}]
```

**Error handling:** If the API call fails, return `{"error": "Could not generate insights"}`. The frontend shows a retry button.

**API key:** Set via `ANTHROPIC_API_KEY` environment variable. If not set, insights drawer shows "Insights unavailable — API key not configured."

**Cache invalidation:** When a user uploads a new month, all existing `insights_cache` rows for that user are deleted. Insight trends reference the full history, so any cached insights for older months may now be stale. The cost of regeneration is acceptable; simplicity of "always fresh after upload" is preferred over partial invalidation.

**Datetime storage:** All `generated_at` timestamps stored as UTC ISO-8601 strings.

---

## Auth Implementation

- Passwords hashed with `bcrypt` (via `flask-bcrypt`)
- Session managed with `flask-login`
- All authenticated routes redirect to `/login` if no session
- No password reset for now

**Registration validation:**
- Username: 3–32 characters, alphanumeric + underscores only
- Password: minimum 8 characters
- On duplicate username: flash error "Username already taken", re-render form with username pre-filled
- On validation failure: flash specific error, re-render form

---

## File Upload Constraints

- Maximum file size: 20 MB (enforced via `MAX_CONTENT_LENGTH` in Flask config)
- Accepted MIME types: `application/pdf` only (validated before passing to pdfplumber)
- Encrypted/password-protected PDFs: pdfplumber will raise an exception → caught and shown as flash error "PDF appears to be password-protected or corrupted."
- Files are written to a temp path, parsed, then deleted regardless of success/failure

## Goals Panel & Chart.js Integration

The "Set My Goals" panel stores numeric targets in `localStorage` (keyed by metric name). On page load, JavaScript reads these values and injects a dashed green dataset line into each Chart.js instance. The dashboard template exposes all chart instances in a `window.charts` registry object (e.g. `window.charts.dischargeLOS`). The goals panel JS calls `chart.data.datasets.push(goalDataset)` and `chart.update()` for each chart where a goal is set. This is the same pattern used in the existing `ED_Provider_Dashboard.html`.

## Error Handling

| Scenario | Behavior |
|----------|----------|
| Wrong PDF (not an ED metrics report) | Flash error: "This doesn't look like an ED Provider Metrics PDF. Please upload the correct file." No data stored. |
| Field missing from PDF | Store `null`; dashboard shows "—" for that metric |
| Duplicate month upload | Overwrite existing row (upsert); flash info: "Month updated." |
| LLM API error | Insights drawer shows error + retry button |
| No months uploaded | Dashboard shows empty state with upload prompt |

---

## Out of Scope (for now)

- Password reset / email verification
- Admin panel
- Peer data pooling across users
- WRVU / physician charges extraction (rendered as charts in PDFs, not text-extractable)
- Mobile-optimized layout
- Export to PDF/CSV
