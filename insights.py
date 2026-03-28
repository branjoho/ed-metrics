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
    'radByDispo':    ('Radiology by Disposition', 'rad_admit_me', 'rad_admit_peers', None, 'Radiology ordering split by admitted vs discharged patients. Admitted patients typically require more imaging.'),
    'esiChart':      ('ESI Acuity Mix', 'esi3', None, None, 'Distribution across ESI levels: 1=critical, 2=emergent, 3=urgent, 4=semi-urgent, 5=non-urgent. ESI-3 is typically the largest group.'),
    'pctTable':      ('Overall Percentile Rankings', 'discharge_los_pctile', None, None, 'Summary of all metric percentile rankings. Lower percentile = better for time/rate metrics; higher = better for productivity.'),
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
