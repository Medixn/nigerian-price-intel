"""
Outlier detection for property listings.

Uses the IQR (Interquartile Range) method — the same approach used in
exploratory data analysis. A listing is considered an outlier if its
price falls outside [Q1 - k*IQR, Q3 + k*IQR] within its peer group.

Peer group = (purpose, bedrooms, canonical_location)

We do NOT delete outliers — we flag them. Users should see them with a
warning so they can judge for themselves (some cheap listings are real
bargains; some are scams; some are typos).

Bulk listings (multiple units leased together) are flagged separately
by the ingestion layer. This module respects those flags and does not
overwrite them.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from src.models import Listing


logger = logging.getLogger(__name__)


# How many IQRs beyond the quartiles counts as an outlier.
# 1.5 is the classic Tukey rule; 2.0 is more permissive.
IQR_MULTIPLIER = 2.0

# We require at least this many peer listings before judging an outlier.
# With 5 listings, the quartiles are meaningless; with 20, they're solid.
MIN_PEER_COUNT = 8

# Reason string used by the ingestion layer for bulk listings.
# We check this exact value to avoid overwriting it.
BULK_REASON = "bulk listing (multiple units)"


@dataclass
class PeerStats:
    """Quartiles and bounds for a peer group."""
    count: int
    q1: float
    median: float
    q3: float
    iqr: float
    lower_bound: float   # below this = suspiciously cheap
    upper_bound: float   # above this = suspiciously expensive


def compute_peer_stats(prices: list[float], k: float = IQR_MULTIPLIER) -> Optional[PeerStats]:
    """
    Compute quartile-based bounds for a list of prices.

    Returns None if there are too few data points to judge.
    """
    n = len(prices)
    if n < MIN_PEER_COUNT:
        return None

    sorted_prices = sorted(prices)
    q1 = _quantile(sorted_prices, 0.25)
    median = _quantile(sorted_prices, 0.50)
    q3 = _quantile(sorted_prices, 0.75)
    iqr = q3 - q1

    return PeerStats(
        count=n,
        q1=q1,
        median=median,
        q3=q3,
        iqr=iqr,
        lower_bound=q1 - k * iqr,
        upper_bound=q3 + k * iqr,
    )


def _quantile(sorted_data: list[float], q: float) -> float:
    """Linear-interpolation quantile. Matches numpy.percentile's default."""
    if not sorted_data:
        raise ValueError("empty data")
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac


def _peer_key(listing: Listing) -> tuple:
    """
    Define the peer group for a listing.

    Peers share:
      - the same purpose (rent/sale)
      - the same bedroom count
      - the same canonical location (e.g. "Lekki Phase 1")

    Listings without a normalized location are grouped under "unknown",
    which prevents them from polluting any specific area's statistics.
    """
    area = "unknown"
    if listing.location_id and listing.location:
        area = listing.location.canonical_name.lower()
    return (listing.purpose, listing.bedrooms, area)


def detect_outliers(session: Session) -> dict:
    """
    Scan all listings in the DB, compute peer statistics, and set the
    is_outlier / outlier_reason flags.

    Returns a summary dict: {"checked": N, "flagged_high": X, "flagged_low": Y,
                              "groups_analyzed": G, "groups_skipped": S}
    """
    # Eager-load the location relationship so we don't hit N+1 queries.
    listings = list(
        session.scalars(
            select(Listing).options(joinedload(Listing.location))
        )
    )

    # Group listings by peer key
    groups: dict[tuple, list[Listing]] = {}
    for listing in listings:
        if listing.price_annual_ngn is None:
            continue
        groups.setdefault(_peer_key(listing), []).append(listing)

    checked = 0
    flagged_high = 0
    flagged_low = 0
    groups_analyzed = 0
    groups_skipped = 0

    for peer_key, peers in groups.items():
        prices = [p.price_annual_ngn for p in peers if p.price_annual_ngn is not None]
        stats = compute_peer_stats(prices)

        if stats is None:
            # Too few peers — skip this group. Do NOT clear flags we
            # didn't set ourselves (e.g. bulk listings).
            groups_skipped += 1
            for listing in peers:
                if listing.outlier_reason == BULK_REASON:
                    continue
                listing.is_outlier = False
                listing.outlier_reason = None
            continue

        groups_analyzed += 1

        for listing in peers:
            checked += 1
            price = listing.price_annual_ngn
            if price is None:
                continue

            # Respect the bulk-listing flag set by the ingestion layer.
            # Bulk listings are not single-unit prices — comparing them to
            # single-unit peers produces false positives.
            if listing.outlier_reason == BULK_REASON:
                continue

            bedrooms_label = listing.bedrooms if listing.bedrooms is not None else "?"

            if price < stats.lower_bound:
                listing.is_outlier = True
                listing.outlier_reason = (
                    f"suspiciously cheap: ₦{price:,.0f}/yr vs median "
                    f"₦{stats.median:,.0f} for {bedrooms_label}-bed "
                    f"in {peer_key[2]}"
                )
                flagged_low += 1
            elif price > stats.upper_bound:
                listing.is_outlier = True
                listing.outlier_reason = (
                    f"suspiciously expensive: ₦{price:,.0f}/yr vs median "
                    f"₦{stats.median:,.0f} for {bedrooms_label}-bed "
                    f"in {peer_key[2]}"
                )
                flagged_high += 1
            else:
                listing.is_outlier = False
                listing.outlier_reason = None

    session.commit()

    return {
        "checked": checked,
        "flagged_high": flagged_high,
        "flagged_low": flagged_low,
        "groups_analyzed": groups_analyzed,
        "groups_skipped": groups_skipped,
    }