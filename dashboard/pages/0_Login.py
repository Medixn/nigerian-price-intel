"""
Login / Signup page with Paystack upgrade flow.
"""
from __future__ import annotations

import _path_setup  # noqa: F401

import streamlit as st
from sqlalchemy import select

from src.db.session import session_scope
from src.models import User
from src.services.auth import authenticate, create_user
from src.services.paystack import (
    PREMIUM_PRICE_NGN,
    initiate_premium_payment,
    verify_and_upgrade,
)


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
    for key in (
        "user_id", "user_email", "user_plan",
        "payment_url", "pending_reference",
    ):
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
            if st.button(
                f"💳 Upgrade for ₦{PREMIUM_PRICE_NGN:,}",
                use_container_width=True,
                type="primary",
            ):
                with session_scope() as session:
                    user = session.execute(
                        select(User).where(User.id == st.session_state["user_id"])
                    ).scalar_one_or_none()

                    if user is None:
                        _logout()
                        st.warning("Session expired. Please sign in again.")
                        st.stop()

                    try:
                        payment_info = initiate_premium_payment(user)
                        st.session_state["pending_reference"] = payment_info["reference"]
                        st.session_state["payment_url"] = payment_info["authorization_url"]
                        st.rerun()
                    except Exception as exc:
                        st.error(f"Could not start payment: {exc}")

    # ---------- Payment-in-progress panel ----------
    if st.session_state.get("payment_url"):
        st.markdown("---")
        st.info(
            "**Payment started.** Click the button below to open Paystack's "
            "secure checkout in a new tab. Complete the payment, then come back "
            "here and click **Verify Payment**."
        )

        st.markdown(
            f"""
            <a href="{st.session_state['payment_url']}" target="_blank" style="
                display: inline-block;
                padding: 14px 28px;
                background-color: #0ba4db;
                color: white;
                text-decoration: none;
                border-radius: 8px;
                font-weight: 700;
                font-size: 1.05rem;
                margin: 8px 0;
            ">💳 Open Paystack Checkout →</a>
            """,
            unsafe_allow_html=True,
        )

        st.caption(
            f"Reference: `{st.session_state['pending_reference']}`"
        )

        col_a, col_b = st.columns(2)
        with col_a:
            if st.button("✅ Verify Payment", type="primary", use_container_width=True):
                with session_scope() as session:
                    user = session.execute(
                        select(User).where(User.id == st.session_state["user_id"])
                    ).scalar_one_or_none()

                    if user is None:
                        _logout()
                        st.warning("Session expired. Please sign in again.")
                        st.stop()

                    result = verify_and_upgrade(
                        session,
                        user,
                        st.session_state["pending_reference"],
                    )

                    if result["success"]:
                        st.session_state["user_plan"] = "premium"
                        st.session_state.pop("payment_url", None)
                        st.session_state.pop("pending_reference", None)
                        st.success(result["message"])
                        st.rerun()
                    else:
                        st.error(result["message"])

        with col_b:
            if st.button("Cancel", use_container_width=True):
                st.session_state.pop("payment_url", None)
                st.session_state.pop("pending_reference", None)
                st.rerun()

    # ---------- Premium info ----------
    if st.session_state.get("user_plan") != "premium":
        st.markdown("---")
        st.markdown("### What you get with Premium")
        st.markdown(
            f"""
            - **Unlimited listing lookups** (free tier: 3 per day)
            - **Full Deal Finder access** (free tier: top 5 results only)
            - **Price-drop alerts** via email
            - **Saved searches** and shortlists
            - **CSV export** of filtered results

            **₦{PREMIUM_PRICE_NGN:,} for 30 days.** Cancel anytime.
            """
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