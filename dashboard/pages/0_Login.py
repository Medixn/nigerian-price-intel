"""Login / Signup page."""
from __future__ import annotations

import _path_setup  # noqa: F401

import streamlit as st
from sqlalchemy import select

from src.db.session import session_scope
from src.models import User
from src.services.auth import authenticate, create_user, upgrade_to_premium


st.set_page_config(
    page_title="Sign In",
    page_icon="🔐",
    layout="centered",
)


# ---------------------------------------------------------------
# Session helpers
# ---------------------------------------------------------------

def _set_logged_in(user_id: int, email: str, plan: str) -> None:
    """Store the logged-in user's essentials in Streamlit session state."""
    st.session_state["user_id"] = user_id
    st.session_state["user_email"] = email
    st.session_state["user_plan"] = plan


def _logout() -> None:
    """Clear all auth-related session state."""
    for key in ("user_id", "user_email", "user_plan"):
        st.session_state.pop(key, None)


def _refresh_session_user() -> None:
    """
    Re-fetch the currently-signed-in user from the DB and update session state.

    If the user no longer exists (deleted, DB reset, etc.), wipe the
    session so the login form shows again.
    """
    user_id = st.session_state.get("user_id")
    if user_id is None:
        return

    with session_scope() as session:
        user = session.execute(
            select(User).where(User.id == user_id)
        ).scalar_one_or_none()

        if user is None:
            _logout()
            return

        st.session_state["user_email"] = user.email
        st.session_state["user_plan"] = user.plan


# ---------------------------------------------------------------
# Page
# ---------------------------------------------------------------

st.title("🔐 Account")

# ---------------- Already signed in ----------------
if "user_id" in st.session_state:
    # Refresh from DB — may wipe the session if the user is gone
    _refresh_session_user()

    if "user_id" not in st.session_state:
        st.warning("Your session expired. Please sign in again.")
        st.stop()

    st.success(
        f"Signed in as **{st.session_state['user_email']}** "
        f"({st.session_state.get('user_plan', 'free')} tier)"
    )

    col1, col2 = st.columns(2)

    with col1:
        if st.button("Log out", use_container_width=True):
            _logout()
            st.rerun()

    with col2:
        if st.session_state.get("user_plan") != "premium":
            if st.button("Upgrade to Premium (demo)", use_container_width=True):
                with session_scope() as session:
                    user = session.execute(
                        select(User).where(User.id == st.session_state["user_id"])
                    ).scalar_one_or_none()

                    if user is None:
                        # Stale session — force re-login
                        _logout()
                        st.warning("Session expired. Please sign in again.")
                        st.stop()

                    upgrade_to_premium(session, user)

                st.session_state["user_plan"] = "premium"
                st.rerun()

    st.info(
        "**Premium tier unlocks:** unlimited listing lookups, saved searches, "
        "and price-drop alerts. (Real payment integration coming soon.)"
    )
    st.stop()


# ---------------- Not signed in ----------------
tab1, tab2 = st.tabs(["Sign in", "Create account"])

with tab1:
    with st.form("login_form"):
        email = st.text_input("Email")
        password = st.text_input("Password", type="password")
        submit = st.form_submit_button("Sign in", use_container_width=True)

        if submit:
            with session_scope() as session:
                user = authenticate(session, email, password)
                if user is None:
                    st.error("Invalid email or password.")
                else:
                    _set_logged_in(user.id, user.email, user.plan)
                    st.rerun()

with tab2:
    with st.form("signup_form"):
        new_email = st.text_input("Email")
        new_name = st.text_input("Display name (optional)")
        new_password = st.text_input("Password", type="password")
        confirm = st.text_input("Confirm password", type="password")
        submit = st.form_submit_button("Create account", use_container_width=True)

        if submit:
            if new_password != confirm:
                st.error("Passwords don't match.")
            elif len(new_password) < 8:
                st.error("Password must be at least 8 characters.")
            else:
                with session_scope() as session:
                    user = create_user(session, new_email, new_password, new_name)
                    if user is None:
                        st.error("That email is already registered.")
                    else:
                        _set_logged_in(user.id, user.email, user.plan)
                        st.rerun()