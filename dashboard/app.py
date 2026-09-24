"""
Nigerian Property Price Intelligence — Market Overview
"""
from __future__ import annotations

# --- PATH BOOTSTRAP ---
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload

from _auth_helpers import current_user
from src.db.session import session_scope
from src.models import Listing, NormalizedLocation, User, Watchlist

st.set_page_config(
    page_title="Nigerian Property Price Intelligence",
    page_icon="🏠",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------
# Data loading — cached so re-renders are fast
# ---------------------------------------------------------------

@st.cache_data(ttl=300)
def load_listings_df() -> pd.DataFrame:
    """Load all rent listings into a DataFrame."""
    with session_scope() as session:
        rows = session.execute(
            select(
                Listing.id,
                Listing.title,
                Listing.bedrooms,
                Listing.price_annual_ngn,
                Listing.raw_location,
                Listing.is_outlier,
                Listing.outlier_reason,
                NormalizedLocation.canonical_name.label("location"),
            )
            .outerjoin(NormalizedLocation, Listing.location_id == NormalizedLocation.id)
            .where(
                Listing.purpose == "rent",
                Listing.price_annual_ngn.isnot(None),
            )
        ).all()

    df = pd.DataFrame(rows, columns=[
        "id", "title", "bedrooms", "price_annual", "raw_location",
        "is_outlier", "outlier_reason", "location",
    ])
    return df


@st.cache_data(ttl=300)
def load_market_stats() -> dict:
    """Compute summary statistics for the KPI cards."""
    with session_scope() as session:
        total = session.scalar(
            select(func.count(Listing.id))
            .where(Listing.purpose == "rent", Listing.price_annual_ngn.isnot(None))
        )
        median_price = session.scalar(
            select(func.avg(Listing.price_annual_ngn))
            .where(Listing.purpose == "rent", Listing.price_annual_ngn.isnot(None))
        )
        flagged = session.scalar(
            select(func.count(Listing.id))
            .where(Listing.is_outlier == True)  # noqa: E712
        )

    return {
        "total": total or 0,
        "median_price": median_price or 0,
        "flagged": flagged or 0,
    }


def _format_ngn_compact(value: float) -> str:
    """Format a naira amount compactly: 12,500,000 -> '₦12.5M'."""
    if value >= 1_000_000_000:
        return f"₦{value / 1_000_000_000:.1f}B"
    if value >= 1_000_000:
        return f"₦{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"₦{value / 1_000:.0f}K"
    return f"₦{value:,.0f}"


# ---------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------

st.title("🏠 Nigerian Property Price Intelligence")
st.caption("Rental market intelligence for Lagos, Abuja, and beyond")

df = load_listings_df()
stats = load_market_stats()

if df.empty:
    st.warning("No listings in the database yet. Run the scraper first.")
    st.stop()

# ---------- KPI cards ----------
col1, col2, col3, col4 = st.columns(4)

with col1:
    with st.container(border=True):
        st.metric("Total Listings", f"{stats['total']:,}")

with col2:
    with st.container(border=True):
        median_rent = df["price_annual"].median()
        st.metric("Median Rent", f"{_format_ngn_compact(median_rent)}/yr")

with col3:
    with st.container(border=True):
        top_area = (
            df.dropna(subset=["location"])["location"].value_counts().idxmax()
            if df["location"].notna().any() else "n/a"
        )
        st.metric("Most Listed Area", top_area)

with col4:
    with st.container(border=True):
        flagged_pct = (stats["flagged"] / stats["total"] * 100) if stats["total"] else 0
        st.metric("Flagged Anomalies", f"{stats['flagged']:,}", f"{flagged_pct:.1f}%")

# ---------- Distribution by bedroom count ----------
st.subheader("Price Distribution by Bedroom Count")
st.caption("Each box shows the middle 50% of listings. Dots are outliers.")

box_df = df[df["bedrooms"].notna() & (df["bedrooms"] <= 6)].copy()
box_df["bedrooms"] = box_df["bedrooms"].astype(int)

if not box_df.empty:
    fig = px.box(
        box_df,
        x="bedrooms",
        y="price_annual",
        color="bedrooms",
        points="outliers",
        labels={"price_annual": "Annual Rent (₦)", "bedrooms": "Bedrooms"},
    )
    fig.update_layout(
        showlegend=False,
        height=420,
        margin=dict(t=20, b=20),
        yaxis_tickformat=",.0f",
    )
    st.plotly_chart(fig, width="stretch")

# ---------- Top areas by median rent ----------
st.subheader("Top Areas by Median Rent")

area_stats = (
    df.dropna(subset=["location"])
    .groupby("location")
    .agg(
        count=("id", "count"),
        median_rent=("price_annual", "median"),
    )
    .reset_index()
    .query("count >= 5")
    .sort_values("median_rent", ascending=False)
    .head(10)
)

if not area_stats.empty:
    fig2 = px.bar(
        area_stats,
        x="median_rent",
        y="location",
        orientation="h",
        text="count",
        labels={"median_rent": "Median Annual Rent (₦)", "location": ""},
        color="median_rent",
        color_continuous_scale="Blues",
    )
    fig2.update_layout(
        showlegend=False,
        height=420,
        margin=dict(t=20, b=20),
        coloraxis_showscale=False,
        yaxis=dict(autorange="reversed"),
    )
    fig2.update_traces(
        texttemplate="%{text} listings",
        textposition="outside",
    )
    st.plotly_chart(fig2, width="stretch")

# ---------- Sample of listings ----------
st.subheader("🎯 Sample of Listings")
st.caption("Filtered to non-outliers with a normalized location.")

sample_df = (
    df[~df["is_outlier"] & df["location"].notna()]
    .sort_values("price_annual")
    .head(20)
    [["id", "bedrooms", "location", "price_annual", "title"]]
    .rename(columns={
        "id": "ID",
        "bedrooms": "Beds",
        "location": "Area",
        "price_annual": "Annual Rent (₦)",
        "title": "Title",
    })
)

st.dataframe(
    sample_df,
    width="stretch",
    hide_index=True,
    column_config={
        "Annual Rent (₦)": st.column_config.NumberColumn(format="₦%d"),
        "Title": st.column_config.TextColumn(width="large"),
    },
)

st.caption(f"Data as of latest scrape · {len(df):,} listings loaded · Use the sidebar to explore")
# ---------- User watchlist (if signed in) ----------
user = current_user()
if user:
    st.markdown("---")
    st.subheader("⭐ Your Watchlist")

    with session_scope() as session:
        rows = session.execute(
            select(Watchlist, Listing)
            .join(Listing, Listing.id == Watchlist.listing_id)
            .where(Watchlist.user_id == user["id"])
        ).all()

        if not rows:
            st.caption(
                "No watched listings yet. Go to **Listing Lookup** and click "
                "'Watch for price drops' on any listing."
            )
        else:
            for w, listing in rows:
                price = listing.price_annual_ngn or 0
                last_seen = w.last_notified_price or price
                change = price - last_seen
                delta_text = ""
                if change != 0:
                    sign = "+" if change > 0 else ""
                    delta_text = f" ({sign}₦{change:,.0f} since you started watching)"

                st.markdown(
                    f"- **{listing.title[:80]}** — ₦{price:,.0f}/yr{delta_text}  "
                    f"[View]({listing.source_url})"
                )