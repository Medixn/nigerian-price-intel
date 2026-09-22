"""
Listing Lookup — full report on a single listing.

Enter a listing ID from the Area Explorer or Deal Finder tables and
see a comprehensive breakdown: peer comparison, percentile rank,
fair range, verdict, and warning flags.
"""
from __future__ import annotations

# --- PATH BOOTSTRAP ---
import _path_setup  # noqa: F401
from _auth_helpers import show_user_badge

import pandas as pd
import plotly.graph_objects as go
import streamlit as st
from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.db.session import session_scope
from src.models import Listing
from src.services.intelligence import estimate_fair_value, score_listing


st.set_page_config(
    page_title="Listing Lookup",
    page_icon="🔎",
    layout="wide",
)


# ---------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------

@st.cache_data(ttl=300)
def load_listing(listing_id: int) -> dict | None:
    """Fetch a listing's full record plus its score."""
    with session_scope() as session:
        listing = session.execute(
            select(Listing)
            .options(joinedload(Listing.location))
            .where(Listing.id == listing_id)
        ).scalar_one_or_none()

        if listing is None:
            return None

        score = score_listing(session, listing)

        # Also grab the full peer group for the comparison chart
        peers_df = _load_peers_for(session, listing)

        return {
            "listing": {
                "id": listing.id,
                "title": listing.title,
                "price_annual": listing.price_annual_ngn,
                "bedrooms": listing.bedrooms,
                "bathrooms": listing.bathrooms,
                "location": listing.location.canonical_name if listing.location else None,
                "raw_location": listing.raw_location,
                "source_url": listing.source_url,
                "is_outlier": listing.is_outlier,
                "outlier_reason": listing.outlier_reason,
                "property_type": listing.property_type,
            },
            "score": score.to_dict(),
            "peers": peers_df,
        }


def _load_peers_for(session, listing: Listing) -> pd.DataFrame:
    """All listings in the same peer group (location + bedrooms, rent)."""
    if listing.location_id is None:
        return pd.DataFrame()

    stmt = select(
        Listing.id,
        Listing.title,
        Listing.price_annual_ngn,
        Listing.source_url,
    ).where(
        Listing.location_id == listing.location_id,
        Listing.purpose == listing.purpose,
        Listing.price_annual_ngn.isnot(None),
    )
    if listing.bedrooms is not None:
        stmt = stmt.where(Listing.bedrooms == listing.bedrooms)
    else:
        stmt = stmt.where(Listing.bedrooms.is_(None))

    rows = session.execute(stmt).all()
    return pd.DataFrame(rows, columns=["id", "title", "price_annual", "source_url"])


@st.cache_data(ttl=300)
def load_recent_listing_ids() -> list[int]:
    """Sample of listing IDs for quick-pick dropdown, cheapest first."""
    with session_scope() as session:
        rows = session.execute(
            select(Listing.id)
            .where(Listing.price_annual_ngn.isnot(None), Listing.purpose == "rent")
            .order_by(Listing.price_annual_ngn)
            .limit(200)
        ).all()
    return [r[0] for r in rows]


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _format_ngn(value: float) -> str:
    if value is None:
        return "—"
    if value >= 1_000_000_000:
        return f"₦{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"₦{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"₦{value / 1_000:.0f}K"
    return f"₦{value:,.0f}"


def _verdict_color(verdict: str) -> str:
    return {
        "below_market": "#2CA02C",
        "fair": "#888888",
        "above_market": "#D62728",
        "suspiciously_cheap": "#E4C441",
        "suspiciously_expensive": "#E4A23A",
        "insufficient_data": "#555555",
    }.get(verdict, "#555555")


def _verdict_emoji(verdict: str) -> str:
    return {
        "below_market": "🟢",
        "fair": "⚪",
        "above_market": "🔴",
        "suspiciously_cheap": "🟡",
        "suspiciously_expensive": "🟠",
        "insufficient_data": "⚫",
    }.get(verdict, "⚫")


# ---------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------

st.title("🔎 Listing Lookup")
st.caption("Get a full report on any listing — is it a good deal?")

# ---------- Input ----------
recent_ids = load_recent_listing_ids()

col1, col2 = st.columns([1, 2])

with col1:
    listing_id = st.number_input(
        "Listing ID",
        min_value=1,
        value=int(recent_ids[0]) if recent_ids else 1,
        step=1,
        help="Copy the ID column from Area Explorer or Deal Finder tables.",
    )

with col2:
    if recent_ids:
        st.caption("Some IDs to try:")
        sample = recent_ids[:5] + recent_ids[len(recent_ids) // 2: len(recent_ids) // 2 + 3]
        st.caption(" · ".join(str(i) for i in sample))

st.divider()

# ---------- Load and score ----------
data = load_listing(int(listing_id))

if data is None:
    st.error(f"No listing with ID {listing_id}. Try another.")
    st.stop()

listing = data["listing"]
score = data["score"]
peers = data["peers"]

# ---------- Listing header ----------
verdict = score.get("verdict", "insufficient_data")
emoji = _verdict_emoji(verdict)
color = _verdict_color(verdict)

st.markdown(f"## {emoji} {listing['title']}")

badges = []
if listing["location"]:
    badges.append(f"📍 **{listing['location']}**")
if listing["bedrooms"]:
    badges.append(f"🛏 {listing['bedrooms']} bed")
if listing["bathrooms"]:
    badges.append(f"🚿 {listing['bathrooms']} bath")
if listing["property_type"]:
    badges.append(f"🏠 {listing['property_type']}")

st.markdown(" · ".join(badges))

if listing["source_url"]:
    st.markdown(f"[Open original listing ↗]({listing['source_url']})")

# ---------- Key stats ----------
st.markdown("### At a glance")

k1, k2, k3, k4 = st.columns(4)

with k1:
    with st.container(border=True):
        st.metric("Annual Rent", _format_ngn(listing["price_annual"]))

with k2:
    with st.container(border=True):
        peer_median = score.get("median")
        st.metric("Peer Median", _format_ngn(peer_median))

with k3:
    with st.container(border=True):
        pct = score.get("percentile")
        st.metric("Percentile", f"{pct:.0f}" if pct is not None else "—")

with k4:
    with st.container(border=True):
        savings_pct = score.get("savings_pct_vs_median")
        if savings_pct is not None:
            sign = "+" if savings_pct > 0 else ""
            st.metric("Vs Median", f"{sign}{savings_pct:.1f}%")
        else:
            st.metric("Vs Median", "—")

# ---------- Verdict panel ----------
st.markdown("### Verdict")

confidence_text = {
    "high": "High confidence",
    "low": "Low confidence",
    "none": "Insufficient data",
}.get(score.get("confidence", "none"), "—")

st.markdown(
    f"""
    <div style="
        border-left: 6px solid {color};
        padding: 16px 20px;
        background-color: rgba(255,255,255,0.03);
        border-radius: 4px;
        margin-bottom: 12px;
    ">
        <div style="font-size: 1.25rem; font-weight: 600; margin-bottom: 6px;">
            {emoji} {score.get('verdict_label', '—')}
        </div>
        <div style="font-size: 0.9rem; opacity: 0.75;">
            {confidence_text} · based on {score.get('peer_count', 0)} comparable listings
        </div>
    </div>
    """,
    unsafe_allow_html=True,
)

# Suspicious warning
if listing["is_outlier"]:
    st.warning(
        f"⚠️ This listing is flagged as anomalous. Reason: "
        f"{listing['outlier_reason'] or 'unknown'}"
    )

if verdict == "insufficient_data":
    st.info(
        "We don't have enough comparable listings to make a confident judgment "
        "on this one. Try a listing in a more popular area."
    )

# ---------- Peer comparison chart ----------
if not peers.empty and peer_median:
    st.markdown("### How it compares to peers")

    # Histogram with a marker on this listing's price
    fig = go.Figure()

    fig.add_trace(go.Histogram(
        x=peers["price_annual"],
        nbinsx=25,
        name="Peers",
        marker_color="#4C78A8",
        opacity=0.8,
    ))

    # Vertical line at this listing's price
    fig.add_vline(
        x=listing["price_annual"],
        line_width=3,
        line_color=color,
        line_dash="solid",
        annotation_text=f"  This listing: {_format_ngn(listing['price_annual'])}",
        annotation_position="top",
        annotation_font_size=12,
        annotation_font_color=color,
    )

    # Vertical dashed line at median
    fig.add_vline(
        x=peer_median,
        line_width=2,
        line_color="#2CA02C",
        line_dash="dash",
        annotation_text=f"  Median: {_format_ngn(peer_median)}",
        annotation_position="bottom",
        annotation_font_size=11,
        annotation_font_color="#2CA02C",
    )

    fig.update_layout(
        height=380,
        margin=dict(t=80, b=60, l=20, r=20),
        xaxis_title="Annual Rent (₦)",
        yaxis_title="Listings",
        xaxis_tickformat=",.0f",
        bargap=0.05,
        showlegend=False,
    )

    st.plotly_chart(fig, width="stretch")

# ---------- Fair range summary ----------
if peer_median:
    q1 = score.get("q1") or 0
    q3 = score.get("q3") or 0

    st.markdown("### Fair value range for this peer group")
    st.markdown(
        f"""
        **₦{q1:,.0f} — ₦{q3:,.0f} per year** (middle 50% of comparable listings)

        - The cheapest peer is **{_format_ngn(score.get('q1'))}** (25th percentile)
        - The most expensive peer is **{_format_ngn(score.get('q3'))}** (75th percentile)
        """
    )

# ---------- Similar listings ----------
if not peers.empty:
    with st.expander(f"See all {len(peers)} comparable listings", expanded=False):
        peers_display = peers.copy()
        peers_display["Rent"] = peers_display["price_annual"].apply(_format_ngn)
        peers_display["Is This"] = peers_display["id"].apply(
            lambda i: "← This one" if i == listing["id"] else ""
        )
        peers_display = peers_display.sort_values("price_annual")
        peers_display = peers_display[["id", "Rent", "title", "Is This", "source_url"]]
        peers_display.columns = ["ID", "Annual Rent", "Title", "", "Link"]

        st.dataframe(
            peers_display,
            width="stretch",
            height=400,
            hide_index=True,
            column_config={
                "Link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
                "Title": st.column_config.TextColumn(width="large"),
                "Annual Rent": st.column_config.TextColumn(width="small"),
                "": st.column_config.TextColumn(width="small"),
            },
        )

st.caption(
    "Verdict thresholds: 🟢 ≤80% of median · ⚪ fair · 🔴 ≥125% of median · "
    "🟡/🟠 flagged as anomalies"
)