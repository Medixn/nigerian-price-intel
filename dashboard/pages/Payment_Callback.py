"""
Payment callback — users land here after Paystack redirects them.

We don't strictly need this page (verification happens on the Login page),
but it gives users a nicer landing spot after payment.
"""
from __future__ import annotations

import _path_setup  # noqa: F401

import streamlit as st

st.set_page_config(page_title="Payment", page_icon="💳")

st.title("💳 Payment Status")

if "user_id" not in st.session_state:
    st.warning("Please sign in to continue.")
    st.stop()

# Paystack appends ?reference=... or ?trxref=... to the callback URL
reference = st.query_params.get("reference") or st.query_params.get("trxref")

if not reference:
    st.info("No payment reference found. If you just paid, go to the Account page to verify.")
    st.stop()

st.success("Payment received! Returning to your account...")
st.session_state["pending_reference"] = reference

# Redirect to the Login page
st.page_link("pages/0_Login.py", label="← Back to Account", icon="🔐")