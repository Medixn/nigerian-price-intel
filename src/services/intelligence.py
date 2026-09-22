"""
Price intelligence: fair value estimation and listing scoring.

Given a listing (or a search query), compute:
  - The peer group's price distribution (quartiles, median, count)
  - The listing's percentile rank within that peer group
  - A human-readable verdict (below_market, fair, above_market, insufficient_data)

This module is the heart of the platform's value proposition: it tells
users whether a price is good, not just what the price is.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Listing, NormalizedLocation


logger = logging.getLogger(__name__)


# --- Verdict thresholds (as fractions of the median) ---
#
# Price ranges by fraction of median:
#
#   ≤ 0.60 median → suspiciously cheap  (likely typo, scam, or unusual unit)
#   ≤ 0.80 median → below market        (genuine good deal)
#   ≥ 1.75 median → suspiciously expensive (likely typo or bulk listing)
#   ≥ 1.25 median → above market        (premium pricing)
#   otherwise     → fair                (within the typical range)

SUSPICIOUSLY_CHEAP_FRACTION = 0.60
BELOW_MARKET_FRACTION = 0.80
ABOVE_MARKET_FRACTION = 1.25
SUSPICIOUSLY_EXPENSIVE_FRACTION = 1.75

# Minimum peers before we give a verdict at all.
MIN_PEERS_FOR_VERDICT = 8

# Minimum peers for a "confident" verdict.
MIN_PEERS_FOR_CONFIDENCE = 15


@dataclass
class FairValueEstimate:
    """The distribution of prices within a peer group."""
    location: str
    bedrooms: Optional[int]
    purpose: str
    peer_count: int
    q1: float
    median: float
    q3: float
    iqr: float
    min_price: float
    max_price: float

    @property
    def fair_range(self) -> tuple[float, float]:
        """The middle 50% of the market — the range most users care about."""
        return (self.q1, self.q3)

    @property
    def has_verdict(self) -> bool:
        return self.peer_count >= MIN_PEERS_FOR_VERDICT

    @property
    def is_high_confidence(self) -> bool:
        return self.peer_count >= MIN_PEERS_FOR_CONFIDENCE

    def __str__(self) -> str:
        return (
            f"FairValueEstimate({self.bedrooms}-bed {self.purpose} in {self.location}, "
            f"n={self.peer_count}, median=₦{self.median:,.0f}, "
            f"IQR=₦{self.q1:,.0f}–₦{self.q3:,.0f})"
        )


@dataclass
class ListingScore:
    """How a single listing compares to its peer group."""
    listing_id: int
    listing_title: str
    price: float
    peer_group: FairValueEstimate
    percentile: Optional[float]
    verdict: str
    verdict_label: str
    confidence: str
    savings_vs_median: Optional[float]
    savings_pct_vs_median: Optional[float]

    def to_dict(self) -> dict:
        return {
            "listing_id": self.listing_id,
            "title": self.listing_title,
            "price": self.price,
            "location": self.peer_group.location,
            "bedrooms": self.peer_group.bedrooms,
            "peer_count": self.peer_group.peer_count,
            "median": self.peer_group.median,
            "q1": self.peer_group.q1,
            "q3": self.peer_group.q3,
            "percentile": self.percentile,
            "verdict": self.verdict,
            "verdict_label": self.verdict_label,
            "confidence": self.confidence,
            "savings_vs_median": self.savings_vs_median,
            "savings_pct_vs_median": self.savings_pct_vs_median,
        }


# ----------------------------------------------------------------
# Public API
# ----------------------------------------------------------------

def estimate_fair_value(
    session: Session,
    location_name: str,
    bedrooms: Optional[int],
    purpose: str = "rent",
) -> Optional[FairValueEstimate]:
    """
    Compute the price distribution for a given (location, bedrooms, purpose).

    Returns None if there are no matching listings at all. Returns a
    FairValueEstimate with peer_count < MIN_PEERS_FOR_VERDICT if the
    sample is too small to judge.
    """
    loc = session.execute(
        select(NormalizedLocation).where(
            NormalizedLocation.canonical_name == location_name
        )
    ).scalar_one_or_none()
    if loc is None:
        return None

    stmt = select(Listing.price_annual_ngn).where(
        Listing.location_id == loc.id,
        Listing.purpose == purpose,
        Listing.price_annual_ngn.isnot(None),
        Listing.is_outlier == False,
    )
    if bedrooms is not None:
        stmt = stmt.where(Listing.bedrooms == bedrooms)
    else:
        stmt = stmt.where(Listing.bedrooms.is_(None))

    prices = [p for p in session.scalars(stmt) if p is not None]
    if not prices:
        return None

    prices.sort()
    return FairValueEstimate(
        location=loc.canonical_name,
        bedrooms=bedrooms,
        purpose=purpose,
        peer_count=len(prices),
        q1=_quantile(prices, 0.25),
        median=_quantile(prices, 0.50),
        q3=_quantile(prices, 0.75),
        iqr=_quantile(prices, 0.75) - _quantile(prices, 0.25),
        min_price=prices[0],
        max_price=prices[-1],
    )


def score_listing(session: Session, listing: Listing) -> ListingScore:
    """
    Score a single listing against its peer group.

    Every listing gets a score — even outliers. That's intentional: users
    want to see "this is priced 40% below market" alongside a warning that
    it might be suspicious.
    """
    price = listing.price_annual_ngn or 0.0

    location_name = "unknown"
    if listing.location_id and listing.location:
        location_name = listing.location.canonical_name

    # Peer prices exclude this listing itself
    peer_stmt = select(Listing.price_annual_ngn).where(
        Listing.purpose == listing.purpose,
        Listing.price_annual_ngn.isnot(None),
        Listing.location_id == listing.location_id,
        Listing.id != listing.id,
    )
    if listing.bedrooms is not None:
        peer_stmt = peer_stmt.where(Listing.bedrooms == listing.bedrooms)
    else:
        peer_stmt = peer_stmt.where(Listing.bedrooms.is_(None))

    peer_prices = [p for p in session.scalars(peer_stmt) if p is not None]

    # Include the listing itself in the distribution for quartile computation,
    # but not in the peer_count for confidence.
    all_prices = sorted(peer_prices + [price])

    peer_group = FairValueEstimate(
        location=location_name,
        bedrooms=listing.bedrooms,
        purpose=listing.purpose,
        peer_count=len(peer_prices),
        q1=_quantile(all_prices, 0.25),
        median=_quantile(all_prices, 0.50),
        q3=_quantile(all_prices, 0.75),
        iqr=_quantile(all_prices, 0.75) - _quantile(all_prices, 0.25),
        min_price=all_prices[0],
        max_price=all_prices[-1],
    )

    if peer_group.peer_count < MIN_PEERS_FOR_VERDICT:
        return ListingScore(
            listing_id=listing.id,
            listing_title=listing.title,
            price=price,
            peer_group=peer_group,
            percentile=None,
            verdict="insufficient_data",
            verdict_label=f"Not enough comparable listings (only {peer_group.peer_count})",
            confidence="none",
            savings_vs_median=None,
            savings_pct_vs_median=None,
        )

    # Percentile rank within peers
    cheaper = sum(1 for p in peer_prices if p < price)
    percentile = (cheaper / len(peer_prices)) * 100

    median = peer_group.median
    savings = price - median
    savings_pct = (savings / median) * 100 if median > 0 else 0.0

    # --- Five-tier verdict ---
    if median <= 0:
        verdict = "fair"
        verdict_label = "Fair price"
    elif price <= median * SUSPICIOUSLY_CHEAP_FRACTION:
        verdict = "suspiciously_cheap"
        pct = (1 - price / median) * 100
        verdict_label = (
            f"Suspiciously cheap — {pct:.0f}% below median. Verify legitimacy."
        )
    elif price <= median * BELOW_MARKET_FRACTION:
        verdict = "below_market"
        pct = (1 - price / median) * 100
        verdict_label = f"Below market — {pct:.0f}% cheaper than median"
    elif price >= median * SUSPICIOUSLY_EXPENSIVE_FRACTION:
        verdict = "suspiciously_expensive"
        pct = (price / median - 1) * 100
        verdict_label = (
            f"Suspiciously expensive — {pct:.0f}% above median. Verify accuracy."
        )
    elif price >= median * ABOVE_MARKET_FRACTION:
        verdict = "above_market"
        pct = (price / median - 1) * 100
        verdict_label = f"Above market — {pct:.0f}% pricier than median"
    else:
        verdict = "fair"
        verdict_label = "Fair price — within the typical range"

    confidence = "high" if peer_group.is_high_confidence else "low"

    return ListingScore(
        listing_id=listing.id,
        listing_title=listing.title,
        price=price,
        peer_group=peer_group,
        percentile=percentile,
        verdict=verdict,
        verdict_label=verdict_label,
        confidence=confidence,
        savings_vs_median=savings,
        savings_pct_vs_median=savings_pct,
    )


def _quantile(sorted_data: list[float], q: float) -> float:
    """Linear-interpolation quantile. Matches numpy.percentile's default."""
    if not sorted_data:
        return 0.0
    n = len(sorted_data)
    if n == 1:
        return sorted_data[0]
    idx = q * (n - 1)
    lo = int(idx)
    hi = min(lo + 1, n - 1)
    frac = idx - lo
    return sorted_data[lo] * (1 - frac) + sorted_data[hi] * frac