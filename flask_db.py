import json
import os
from datetime import datetime, timezone, timedelta
from supabase import create_client, Client

def get_client() -> Client:
    return create_client(
        os.environ["SUPABASE_URL"],
        os.environ["SUPABASE_KEY"],
    )


# ---------------------------------------------------------------------------
# Users
# ---------------------------------------------------------------------------

def get_user(username: str) -> dict | None:
    sb = get_client()
    res = sb.table("users").select("*").eq("username", username).execute()
    return res.data[0] if res.data else None


def get_user_by_id(user_id: int) -> dict | None:
    sb = get_client()
    res = sb.table("users").select("*").eq("id", user_id).execute()
    return res.data[0] if res.data else None


def create_user(username: str, password_hash: str) -> dict:
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
    "lab_admit_me", "lab_admit_peers",
    "lab_disc_me", "lab_disc_peers",
    "shift_count",
    "esi1", "esi2", "esi3", "esi4", "esi5",
    "billing_level3", "billing_level4", "billing_level5",
    "shift_data",
]


def get_metrics(user_id: int) -> list[dict]:
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


def upsert_metrics(user_id: int, metrics: dict) -> None:
    sb = get_client()
    m = dict(metrics)
    if isinstance(m.get("shift_data"), list):
        m["shift_data"] = json.dumps(m["shift_data"])
    row = {"user_id": user_id, "month": m["month"], "year": m["year"]}
    for f in METRIC_FIELDS:
        row[f] = m.get(f)
    sb.table("monthly_metrics").upsert(row, on_conflict="user_id,month,year").execute()
    # Clear all cached insights for this user after any upload
    sb.table("insights_cache").delete().eq("user_id", user_id).execute()


def delete_month(user_id: int, month: int, year: int) -> bool:
    sb = get_client()
    res = (
        sb.table("monthly_metrics")
        .select("id")
        .eq("user_id", user_id)
        .eq("month", month)
        .eq("year", year)
        .execute()
    )
    if not res.data:
        return False
    sb.table("insights_cache").delete().eq("user_id", user_id).eq("month", month).eq("year", year).execute()
    sb.table("monthly_metrics").delete().eq("user_id", user_id).eq("month", month).eq("year", year).execute()
    return True


# ---------------------------------------------------------------------------
# Chart notes
# ---------------------------------------------------------------------------

def get_all_notes(user_id: int) -> dict:
    sb = get_client()
    res = sb.table("chart_notes").select("*").eq("user_id", user_id).execute()
    notes = {}
    for r in res.data or []:
        key = f"{r['chart_key']}_{r['month']}_{r['year']}"
        notes[key] = r
    return notes


def upsert_note(user_id: int, month: int, year: int, chart_key: str, text: str) -> None:
    sb = get_client()
    now = datetime.now(timezone.utc).isoformat()
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
        sb.table("chart_notes").update(
            {"note_text": text, "updated_at": now}
        ).eq("user_id", user_id).eq("month", month).eq("year", year).eq("chart_key", chart_key).execute()
    else:
        sb.table("chart_notes").insert({
            "user_id": user_id,
            "month": month,
            "year": year,
            "chart_key": chart_key,
            "note_text": text,
            "created_at": now,
            "updated_at": now,
        }).execute()


def delete_note(user_id: int, month: int, year: int, chart_key: str) -> None:
    sb = get_client()
    sb.table("chart_notes").delete().eq("user_id", user_id).eq("month", month).eq("year", year).eq("chart_key", chart_key).execute()


# ---------------------------------------------------------------------------
# Insights cache
# ---------------------------------------------------------------------------

def get_cached_insight(user_id: int, month: int, year: int, chart_key: str) -> list | None:
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


def save_insight_cache(user_id: int, month: int, year: int, chart_key: str, insights: list) -> None:
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


def get_all_insights(user_id: int) -> list[dict]:
    sb = get_client()
    res = (
        sb.table("insights_cache")
        .select("month, year, chart_key, insight_text")
        .eq("user_id", user_id)
        .execute()
    )
    return res.data or []
