# Streamlit Migration Design

**Date:** 2026-03-27
**Goal:** Replace the Flask app with a Streamlit multi-page app deployed to Streamlit Cloud, making the dashboard accessible via public URL without running a local server.

---

## Architecture

Replace Flask entirely. The app becomes a Streamlit multi-page app backed by Supabase (hosted Postgres) instead of local SQLite.

```
ed-metrics/
├── streamlit_app.py          # entry point, login gate
├── pages/
│   ├── 1_Dashboard.py        # charts + AI insights
│   └── 2_Upload.py           # PDF upload + parse
├── db.py                     # Supabase/Postgres queries
├── parse_pdf.py              # unchanged
├── requirements.txt          # updated with streamlit, supabase-py, plotly
└── .env                      # SUPABASE_URL, SUPABASE_KEY, ANTHROPIC_API_KEY
```

**Auth:** `streamlit-authenticator` handles username/password login. Credentials stored in Supabase `users` table (bcrypt hashed, same as today). Each user only sees their own rows.

**Database:** Supabase Postgres with the same schema as the current SQLite DB. `db.py` wraps all queries.

**Deployment:** Push to GitHub → connect on Streamlit Cloud → add secrets → live URL.

---

## Pages & Components

### `streamlit_app.py` — Login Gate
Renders username/password form via `streamlit-authenticator`. On success, sets `st.session_state` with `user_id` and `username`. All pages check session state and redirect to login if unauthenticated.

### `pages/1_Dashboard.py`
- Month selector (dropdown) — choose which month to view
- KPI cards row — key metrics with peer comparison and percentile badge
- Plotly line charts for each metric (discharge LOS, admission rate, returns, etc.) with me vs peers lines
- AI insights — expandable panel per chart, calling same Claude API logic (reuse `_build_insights_prompt`)
- Percentile summary table

### `pages/2_Upload.py`
- PDF file uploader (`st.file_uploader`, PDF only)
- Calls `parse_metrics()` from `parse_pdf.py` on upload
- Shows parsed values for user review
- Saves to Supabase on confirm

### `db.py`
Thin wrapper around `supabase-py` client. Functions:
- `get_user(username)` / `create_user(username, pw_hash)`
- `get_metrics(user_id)` — returns all monthly rows sorted by year, month
- `upsert_metrics(user_id, month, year, data)`
- `get_insights_cache(user_id, month, year, chart_key)`
- `upsert_insights_cache(user_id, month, year, chart_key, text)`

---

## Data Flow

1. User logs in → `st.session_state` stores `user_id` and `username`
2. Dashboard queries Supabase for all rows matching `user_id`, builds month list
3. Month selector updates `st.session_state.sel_idx` → charts and KPI cards re-render
4. AI insights: check `insights_cache` first (90-day TTL), call Claude on miss, cache result
5. Upload: PDF → `parse_metrics()` → preview table → user confirms → `upsert_metrics()` to Supabase

---

## Error Handling

- **PDF parse failure:** show `st.error()`, do not save
- **Missing Anthropic key:** insights panel shows "unavailable" (same as today)
- **Supabase connection error:** surface as `st.error()` with message
- **Duplicate month upload:** Supabase upsert replaces existing row (matches current `UNIQUE(user_id, month, year)` behavior)

---

## Testing

- Existing `tests/` pytest suite for `parse_pdf.py` — unchanged
- `db.py` functions testable against Supabase test project or local Postgres
- Streamlit UI verified manually
