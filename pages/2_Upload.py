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
