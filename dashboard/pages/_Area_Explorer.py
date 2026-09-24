"""
Area Explorer — drill into a specific area + bedroom count.

Pick an area and bedroom count, see the fair value distribution
and every listing in that bucket with verdict badges.
"""
from __future__ import annotations

# --- PATH BOOTSTRAP ---
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from _auth_helpers import show_user_badge

from collections import Counter

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from src.db.session import session_scope
from src.models import Listing, NormalizedLocation


st.set_page_config(
    page_title="Area Explorer",
    page_icon="🔍",
    layout="wide",
)


# ---------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------

@st.cache_data(ttl=300)
def load_locations() -> list[str]:
    """Distinct canonical location names, ordered by listing count."""
    with session_scope() as session:
        rows = session.execute(
            select(NormalizedLocation.canonical_name)
            .join(Listing, Listing.location_id == NormalizedLocation.id)
            .where(Listing.purpose == "rent", Listing.price_annual_ngn.isnot(None))
        ).all()
    counts = Counter(name for (name,) in rows if name)
    return [name for name, _ in counts.most_common()]


@st.cache_data(ttl=300)
def load_listings_for_area(location: str) -> pd.DataFrame:
    """All rent listings in a specific canonical location."""
    with session_scope() as session:
        loc = session.execute(
            select(NormalizedLocation).where(
                NormalizedLocation.canonical_name == location
            )
        ).scalar_one_or_none()
        if loc is None:
            return pd.DataFrame()

        rows = session.execute(
            select(
                Listing.id,
                Listing.title,
                Listing.bedrooms,
                Listing.bathrooms,
                Listing.price_annual_ngn,
                Listing.is_outlier,
                Listing.outlier_reason,
                Listing.source_url,
            )
            .where(
                Listing.location_id == loc.id,
                Listing.purpose == "rent",
                Listing.price_annual_ngn.isnot(None),
            )
            .order_by(Listing.price_annual_ngn)
        ).all()

    return pd.DataFrame(rows, columns=[
        "id", "title", "bedrooms", "bathrooms",
        "price_annual", "is_outlier", "outlier_reason", "source_url",
    ])


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _format_ngn(value: float) -> str:
    """Format a naira value compactly."""
    if value >= 1_000_000_000:
        return f"₦{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"₦{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"₦{value / 1_000:.0f}K"
    return f"₦{value:,.0f}"


def _verdict_badge(row: pd.Series, median: float) -> str:
    """Return an emoji verdict based on price vs median."""
    if pd.isna(row["price_annual"]) or median == 0:
        return "⚫"
    if row["is_outlier"]:
        return "🟠" if row["price_annual"] > median else "🟡"
    ratio = row["price_annual"] / median
    if ratio <= 0.80:
        return "🟢"
    if ratio >= 1.25:
        return "🔴"
    return "⚪"


def _kpi_card(label: str, value: str) -> None:
    """Render a KPI metric inside a bordered container."""
    with st.container(border=True):
        st.metric(label, value)


# ---------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------

st.title("🔍 Area Explorer")
st.caption("Pick an area and bedroom count to see the full price picture")

locations = load_locations()
if not locations:
    st.warning("No listings in the database yet.")
    st.stop()

# ---------- Filters ----------
col1, col2 = st.columns([2, 1])

with col1:
    selected_area = st.selectbox("Area", locations, index=0)

with col2:
    bedroom_options = ["All"] + [str(i) for i in range(1, 7)]
    selected_bedrooms = st.selectbox("Bedrooms", bedroom_options, index=0)

# ---------- Load data ----------
area_df = load_listings_for_area(selected_area)
if area_df.empty:
    st.warning(f"No listings found in {selected_area}.")
    st.stop()

if selected_bedrooms != "All":
    beds_int = int(selected_bedrooms)
    filtered_df = area_df[area_df["bedrooms"] == beds_int].copy()
else:
    filtered_df = area_df.copy()

if filtered_df.empty:
    st.info(
        f"No {selected_bedrooms}-bedroom listings in {selected_area}. "
        "Try a different filter combination."
    )
    st.stop()

# ---------- Fair value summary ----------
clean = filtered_df[~filtered_df["is_outlier"]]
prices = clean["price_annual"].dropna()

if len(prices) == 0:
    st.warning("Only outliers available — can't compute fair value.")
    st.stop()

q1 = prices.quantile(0.25)
median = prices.median()
q3 = prices.quantile(0.75)
peer_count = len(prices)

st.markdown(
    f"### {selected_area}"
    + (f" · {selected_bedrooms} bed" if selected_bedrooms != "All" else "")
)

k1, k2, k3, k4 = st.columns(4)

with k1:
    _kpi_card("Median Rent", f"{_format_ngn(median)}/yr")
with k2:
    with st.container(border=True):
        st.markdown(
            f"**Fair Range**  \n"
            f"<span style='font-size: 1.5rem; font-weight: 600;'>"
            f"{_format_ngn(q1)} – {_format_ngn(q3)}"
            f"</span>",
            unsafe_allow_html=True,
        )
with k3:
    _kpi_card("Cheapest", f"{_format_ngn(prices.min())}/yr")
with k4:
    _kpi_card("Comparable Listings", f"{peer_count}")

# ---------- Distribution chart ----------
st.subheader("Price Distribution")

hist_df = filtered_df[["price_annual", "is_outlier"]].copy()
hist_df["status"] = hist_df["is_outlier"].map({True: "Flagged", False: "Normal"})

fig = px.histogram(
    hist_df,
    x="price_annual",
    nbins=25,
    color="status",
    labels={"price_annual": "Annual Rent (₦)", "status": ""},
    color_discrete_map={"Normal": "#4C78A8", "Flagged": "#E4A23A"},
)

fig.add_vline(
    x=median,
    line_dash="dash",
    line_color="#2CA02C",
    line_width=2,
    annotation_text=f"Median {_format_ngn(median)}",
    annotation_position="top",
    annotation_font_size=12,
    annotation_font_color="#2CA02C",
)
fig.update_layout(
    height=420,
    margin=dict(t=60, b=120, l=20, r=20),
    xaxis_tickformat=",.0f",
    xaxis_title="Annual Rent (₦)",
    bargap=0.05,
    legend=dict(
        orientation="h",
        yanchor="top",
        y=-0.30,
        xanchor="center",
        x=0.5,
        title=None,
    ),
    yaxis_title="Listings",
)

st.plotly_chart(fig, width="stretch")

# ---------- Listings table ----------
st.subheader(f"Listings in {selected_area}")

display_df = filtered_df.copy()
display_df["Verdict"] = display_df.apply(
    lambda row: _verdict_badge(row, median), axis=1
)
display_df = display_df.sort_values("price_annual")

display_df["Annual Rent"] = display_df["price_annual"].apply(_format_ngn)
display_df["% vs median"] = display_df["price_annual"].apply(
    lambda p: f"{(p / median - 1) * 100:+.0f}%" if median > 0 else "—"
)

table_df = display_df[[
    "Verdict", "Annual Rent", "% vs median", "bedrooms", "bathrooms",
    "title", "source_url",
]].rename(columns={
    "bedrooms": "Beds",
    "bathrooms": "Baths",
    "title": "Title",
    "source_url": "Link",
})

st.dataframe(
    table_df,
    width="stretch",
    height=600,
    hide_index=True,
    column_config={
        "Link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
        "Title": st.column_config.TextColumn(width="large"),
        "Verdict": st.column_config.TextColumn(width="small"),
        "Annual Rent": st.column_config.TextColumn(width="small"),
        "% vs median": st.column_config.TextColumn(width="small"),
    },
)

st.caption(
    f"Showing {len(filtered_df)} listings · "
    f"🟢 below market · ⚪ fair · 🔴 above market · "
    f"🟡/🟠 flagged as anomalous"
)