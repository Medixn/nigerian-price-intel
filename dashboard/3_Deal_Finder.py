"""Deal Finder — diagnostic version. Prints breadcrumbs at every step."""
from __future__ import annotations

import _path_setup  # noqa: F401

import pandas as pd
import streamlit as st
from sqlalchemy import select

from src.db.session import session_scope
from src.models import Listing, NormalizedLocation


st.set_page_config(page_title="Deal Finder", page_icon="🎯", layout="wide")

st.write("### BREADCRUMB 1: module loaded")

# ---------------------------------------------------------------
# Load data
# ---------------------------------------------------------------
st.write("### BREADCRUMB 2: calling load_all_listings()")


@st.cache_data(ttl=300)
def load_all_listings() -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(
                Listing.id,
                Listing.title,
                Listing.bedrooms,
                Listing.bathrooms,
                Listing.price_annual_ngn,
                Listing.is_outlier,
                Listing.source_url,
                NormalizedLocation.canonical_name.label("location"),
            )
            .outerjoin(NormalizedLocation, Listing.location_id == NormalizedLocation.id)
            .where(Listing.purpose == "rent", Listing.price_annual_ngn.isnot(None))
        ).all()

    df = pd.DataFrame(rows, columns=[
        "id", "title", "bedrooms", "bathrooms", "price_annual",
        "is_outlier", "source_url", "location",
    ])
    return df


df = load_all_listings()
st.write(f"### BREADCRUMB 3: loaded {len(df)} rows")

if df.empty:
    st.warning("No listings in the database.")
    st.stop()

# ---------------------------------------------------------------
# Cast bedrooms
# ---------------------------------------------------------------
st.write("### BREADCRUMB 4: casting bedrooms")
df["bedrooms"] = df["bedrooms"].astype("Int64")

# ---------------------------------------------------------------
# Compute peer medians
# ---------------------------------------------------------------
st.write("### BREADCRUMB 5: computing peer medians")
clean = df[~df["is_outlier"]]
st.write(f"  clean rows: {len(clean)}")

medians = (
    clean.groupby(["location", "bedrooms"], dropna=True)["price_annual"]
    .median()
    .to_dict()
)
st.write(f"  peer groups: {len(medians)}")

df["peer_median"] = df.apply(
    lambda r: medians.get((r["location"], r["bedrooms"])),
    axis=1,
)
st.write("### BREADCRUMB 6: peer medians assigned")

df["discount_pct"] = df.apply(
    lambda r: (r["price_annual"] / r["peer_median"] - 1) * 100
    if pd.notna(r["peer_median"]) and r["peer_median"] > 0 else None,
    axis=1,
)
st.write("### BREADCRUMB 7: discount_pct computed")
st.write(f"  rows with discount: {df['discount_pct'].notna().sum()}")

# ---------------------------------------------------------------
# Filters
# ---------------------------------------------------------------
st.write("### BREADCRUMB 8: rendering filters")

available = sorted(df["location"].dropna().unique().tolist())
st.write(f"  available locations: {len(available)}")

selected_locations = st.multiselect("Areas", available, default=[])
st.write("### BREADCRUMB 9: multiselect rendered")

selected_bedrooms = st.selectbox("Bedrooms", ["Any", "1", "2", "3", "4", "5"], index=0)
st.write("### BREADCRUMB 10: bedrooms selectbox rendered")

price_min = int(df["price_annual"].min())
price_max = int(df["price_annual"].max())
st.write(f"  price range: {price_min} – {price_max}")

step = max(500_000, (price_max - price_min) // 100) if price_max > price_min else 500_000
st.write(f"  step: {step}")

price_cap = st.slider(
    "Max price (₦/yr)",
    min_value=price_min,
    max_value=price_max,
    value=price_max,
    step=step,
)
st.write("### BREADCRUMB 11: price slider rendered")

show_suspicious = st.checkbox("Show suspicious", value=False)
st.write("### BREADCRUMB 12: checkbox rendered")

# ---------------------------------------------------------------
# Apply filters
# ---------------------------------------------------------------
st.write("### BREADCRUMB 13: applying filters")

filtered = df.copy()
if selected_locations:
    filtered = filtered[filtered["location"].isin(selected_locations)]
if selected_bedrooms != "Any":
    filtered = filtered[filtered["bedrooms"] == int(selected_bedrooms)]
filtered = filtered[filtered["price_annual"] <= price_cap]
if not show_suspicious:
    filtered = filtered[~filtered["is_outlier"]]
filtered = filtered.dropna(subset=["discount_pct"])

st.write(f"### BREADCRUMB 14: {len(filtered)} rows after filters")

if filtered.empty:
    st.info("No listings match these filters.")
    st.stop()

st.write("### BREADCRUMB 15: rendering KPIs")
st.write(f"  median: {filtered['price_annual'].median()}")

st.write("### BREADCRUMB 16: rendering table")
st.write(filtered.head(3))

st.success("Page rendered successfully!")