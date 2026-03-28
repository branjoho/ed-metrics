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
    """Return field value, or None if not present."""
    return row.get(field)


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
    color = _pctile_color(pctile, higher_is_better=higher_better)
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
render_note_widget("pctTable", sel)

st.markdown("---")

# ── AI Overview ───────────────────────────────────────────────────────────────
st.subheader("Monthly Summary — " + sel_label)
render_insight_panel("overview", sel, rows)
render_note_widget("overview", sel)

# ── Delete month ──────────────────────────────────────────────────────────────
st.markdown("---")
with st.expander("Danger zone"):
    st.warning(f"Delete **{sel_label}** data permanently?")
    if st.button("Delete this month", type="secondary"):
        db.delete_month(user_id, sel["month"], sel["year"])
        st.success(f"{sel_label} deleted.")
        st.rerun()
