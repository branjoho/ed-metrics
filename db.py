import json
from datetime import datetime, timezone, timedelta
import streamlit as st
from supabase import create_client, Client


@st.cache_resource
def get_client() -> Client:
    """Return a cached Supabase client, created once per server process."""
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
    """Insert or update a chart note, preserving the original created_at on updates."""
    sb = get_client()
    now = datetime.now(timezone.utc).isoformat()
    # Check if note exists
    res = (
        sb.table("chart_notes")
        .select("id")
        .eq("user_id", user_id)
        .eq("month", month)
        .eq("year", year)
        .eq("chart_key", chart_key)
        .execute()
    )
    if res.data:
        # Update existing — only set note_text and updated_at
        sb.table("chart_notes").update(
            {"note_text": text, "updated_at": now}
        ).eq("user_id", user_id).eq("month", month).eq("year", year).eq(
            "chart_key", chart_key
        ).execute()
    else:
        # Insert new — set both timestamps
        sb.table("chart_notes").insert(
            {
                "user_id": user_id,
                "month": month,
                "year": year,
                "chart_key": chart_key,
                "note_text": text,
                "created_at": now,
                "updated_at": now,
            }
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
    generated_at = datetime.fromisoformat(row["generated_at"].replace("Z", "+00:00"))
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
