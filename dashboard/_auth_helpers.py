"""Shared authentication helpers for dashboard pages."""
from __future__ import annotations

import streamlit as st


def current_user() -> dict | None:
    """Return the logged-in user's session state, or None."""
    if "user_id" not in st.session_state:
        return None
    return {
        "id": st.session_state["user_id"],
        "email": st.session_state.get("user_email"),
        "plan": st.session_state.get("user_plan", "free"),
    }


def require_login() -> dict:
    """
    Ensure the user is logged in. If not, show a message and stop.
    Returns the user dict on success.
    """
    user = current_user()
    if user is None:
        st.warning("Please sign in from the **Account** page to use this feature.")
        st.stop()
    return user


def require_premium() -> dict:
    """
    Ensure the user is on the premium plan.
    Returns the user dict on success; stops the page otherwise.
    """
    user = require_login()
    if user["plan"] != "premium":
        st.warning(
            "**Premium feature.** Upgrade on the **Account** page to access this."
        )
        st.stop()
    return user


def show_user_badge() -> None:
    """Render a small 'signed in as' badge in the sidebar."""
    user = current_user()
    with st.sidebar:
        st.markdown("---")
        if user is None:
            st.caption("Not signed in")
        else:
            plan_badge = "⭐ Premium" if user["plan"] == "premium" else "Free"
            st.caption(f"👤 {user['email']}")
            st.caption(f"Plan: {plan_badge}")