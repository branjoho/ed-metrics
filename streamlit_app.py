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
