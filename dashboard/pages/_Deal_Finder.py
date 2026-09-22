"""
Deal Finder — surface the best-value listings across the market.

Filters: area (multi-select), bedrooms, max price, include/exclude
suspicious listings. Sorts by "value score" = how far below peer
median the listing is.
"""
from __future__ import annotations

# --- PATH BOOTSTRAP ---
import _path_setup  # noqa: F401
from _auth_helpers import show_user_badge

import pandas as pd
import plotly.express as px
import streamlit as st
from sqlalchemy import select

from src.db.session import session_scope
from src.models import Listing, NormalizedLocation


st.set_page_config(
    page_title="Deal Finder",
    page_icon="🎯",
    layout="wide",
)


# ---------------------------------------------------------------
# Data loading
# ---------------------------------------------------------------

@st.cache_data(ttl=300)
def load_all_listings() -> pd.DataFrame:
    """All rent listings with normalized locations."""
    with session_scope() as session:
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
                NormalizedLocation.canonical_name.label("location"),
            )
            .outerjoin(NormalizedLocation, Listing.location_id == NormalizedLocation.id)
            .where(
                Listing.purpose == "rent",
                Listing.price_annual_ngn.isnot(None),
            )
        ).all()

    return pd.DataFrame(rows, columns=[
        "id", "title", "bedrooms", "bathrooms", "price_annual",
        "is_outlier", "outlier_reason", "source_url", "location",
    ])


# ---------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------

def _format_ngn(value: float) -> str:
    if value >= 1_000_000_000:
        return f"₦{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"₦{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"₦{value / 1_000:.0f}K"
    return f"₦{value:,.0f}"


def _compute_peer_medians(df: pd.DataFrame) -> pd.Series:
    """
    For each row, compute the median price of its peer group
    (same location + bedrooms), excluding outliers.

    Returns a Series aligned with df.index.
    """
    clean = df[~df["is_outlier"]]
    medians = (
        clean.groupby(["location", "bedrooms"])["price_annual"]
        .median()
        .to_dict()
    )
    return df.apply(
        lambda row: medians.get((row["location"], row["bedrooms"])),
        axis=1,
    )


def _verdict_for_row(row: pd.Series, median: float | None) -> str:
    """Return emoji + short label describing how this listing compares to market."""
    if median is None or pd.isna(median) or median == 0:
        return "⚫ No peers"
    ratio = row["price_annual"] / median
    if row["is_outlier"]:
        return "🟠 Above (flag)" if ratio > 1 else "🟡 Below (flag)"
    if ratio <= 0.60:
        return "🟡 Susp. cheap"
    if ratio <= 0.80:
        return "🟢 Below"
    if ratio <= 1.25:
        return "⚪ Fair"
    if ratio <= 1.75:
        return "🔴 Above"
    return "🟠 Susp. exp."


# ---------------------------------------------------------------
# Page layout
# ---------------------------------------------------------------

st.title("🎯 Deal Finder")
st.caption("Find the best-value listings across the whole market")

df = load_all_listings()
if df.empty:
    st.warning("No listings in the database yet.")
    st.stop()

# Attach peer medians once, reuse everywhere
df = df.copy()
df["peer_median"] = _compute_peer_medians(df)
df["discount_pct"] = df.apply(
    lambda r: (r["price_annual"] / r["peer_median"] - 1) * 100
    if pd.notna(r["peer_median"]) and r["peer_median"] > 0 else None,
    axis=1,
)

# ---------- Filters ----------
st.markdown("### Filters")

f1, f2, f3, f4 = st.columns([2, 1, 2, 1])

with f1:
    available_locations = sorted(df["location"].dropna().unique())
    selected_locations = st.multiselect(
        "Areas (leave empty for all)",
        available_locations,
        default=[],
    )

with f2:
    bedroom_options = ["Any"] + [str(i) for i in range(1, 7)]
    selected_bedrooms = st.selectbox("Bedrooms", bedroom_options, index=0)

with f3:
    price_min = int(df["price_annual"].min())
    price_max = int(df["price_annual"].max())
    price_cap = st.slider(
        "Max price (₦/yr)",
        min_value=price_min,
        max_value=price_max,
        value=price_max,
        step=max(500_000, (price_max - price_min) // 100),
        format="₦%d",
    )

with f4:
    show_suspicious = st.checkbox(
        "Show suspicious",
        value=False,
        help="Include listings flagged as suspiciously cheap or expensive.",
    )

# ---------- Apply filters ----------
filtered = df.copy()

if selected_locations:
    filtered = filtered[filtered["location"].isin(selected_locations)]

if selected_bedrooms != "Any":
    filtered = filtered[filtered["bedrooms"] == int(selected_bedrooms)]

filtered = filtered[filtered["price_annual"] <= price_cap]

# Handle suspicious/outlier listings
if not show_suspicious:
    filtered = filtered[
        (~filtered["is_outlier"]) &
        (filtered["discount_pct"].between(-40, 60) | filtered["discount_pct"].isna())
    ]

if filtered.empty:
    st.info(
        "No listings match these filters. Try widening your price cap, "
        "or checking 'Show suspicious'."
    )
    st.stop()

# ---------- Summary ----------
st.markdown("### Summary")

s1, s2, s3, s4 = st.columns(4)

with s1:
    with st.container(border=True):
        st.metric("Matching Listings", f"{len(filtered):,}")

with s2:
    with st.container(border=True):
        st.metric("Median (of results)", _format_ngn(filtered["price_annual"].median()))

with s3:
    with st.container(border=True):
        below = filtered[filtered["discount_pct"] < -10]
        st.metric("Below Market", f"{len(below):,}")

with s4:
    with st.container(border=True):
        cheapest = filtered["price_annual"].min()
        st.metric("Cheapest", _format_ngn(cheapest))

# ---------- Best value list ----------
st.markdown("### 🏆 Best Value Listings")
st.caption(
    "Sorted by discount vs peer median. Green = genuinely below market, "
    "yellow/orange = flagged as suspicious."
)

scored = filtered.dropna(subset=["discount_pct"]).copy()
scored = scored.sort_values("discount_pct")

scored["Verdict"] = scored.apply(
    lambda r: _verdict_for_row(r, r["peer_median"]), axis=1
)
scored["Rent"] = scored["price_annual"].apply(_format_ngn)
scored["Peer"] = scored["peer_median"].apply(_format_ngn)
scored["Discount"] = scored["discount_pct"].apply(lambda x: f"{x:+.0f}%")

table = scored[[
    "Verdict", "Rent", "Discount", "Peer",
    "bedrooms", "bathrooms", "location", "title", "source_url",
]].rename(columns={
    "bedrooms": "Beds",
    "bathrooms": "Baths",
    "location": "Area",
    "title": "Title",
    "source_url": "Link",
})

st.dataframe(
    table,
    width="stretch",
    height=700,
    hide_index=True,
    column_config={
        "Link": st.column_config.LinkColumn("Link", display_text="Open ↗"),
        "Title": st.column_config.TextColumn(width="large"),
        "Area": st.column_config.TextColumn(width="medium"),
        "Verdict": st.column_config.TextColumn(width="medium"),
        "Rent": st.column_config.TextColumn(width="small"),
        "Discount": st.column_config.TextColumn(width="small"),
        "Peer": st.column_config.TextColumn(width="small"),
    },
)

# ---------- Secondary chart: distribution of discounts ----------
st.markdown("### How the market is distributed")
st.caption(
    "The discount distribution across all matching listings. "
    "Anything left of zero is below its peer median."
)

chart_df = scored[["discount_pct"]].dropna()

if not chart_df.empty:
    fig = px.histogram(
        chart_df,
        x="discount_pct",
        nbins=40,
        labels={"discount_pct": "Discount vs peer median (%)"},
        color_discrete_sequence=["#4C78A8"],
    )
    fig.add_vline(
        x=0,
        line_dash="dash",
        line_color="#2CA02C",
        line_width=2,
        annotation_text="Peer median",
        annotation_position="top",
        annotation_font_color="#2CA02C",
    )
    fig.update_layout(
        height=320,
        margin=dict(t=60, b=60, l=20, r=20),
        yaxis_title="Listings",
        bargap=0.05,
    )
    st.plotly_chart(fig, width="stretch")

st.caption(
    f"Showing {len(table):,} listings matching your filters · "
    "🟢 below · ⚪ fair · 🔴 above · 🟡/🟠 flagged"
)