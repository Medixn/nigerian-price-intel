"""
Score listings against their peer groups and print verdicts.

Usage:
    python -m scripts.score_listings --id 42
    python -m scripts.score_listings --all --limit 30
    python -m scripts.score_listings --query "Lekki Phase 1" --bedrooms 2
"""
from __future__ import annotations

import argparse

from sqlalchemy import select
from sqlalchemy.orm import joinedload

from src.db.session import session_scope
from src.models import Listing
from src.services.intelligence import (
    estimate_fair_value,
    score_listing,
)


EMOJI = {
    "below_market": "🟢",
    "fair": "⚪",
    "above_market": "🔴",
    "suspiciously_cheap": "🟡",
    "suspiciously_expensive": "🟠",
    "insufficient_data": "⚫",
}


def cmd_single(listing_id: int) -> None:
    with session_scope() as session:
        listing = session.execute(
            select(Listing)
            .options(joinedload(Listing.location))
            .where(Listing.id == listing_id)
        ).scalar_one_or_none()

        if listing is None:
            print(f"[ERROR] No listing with id={listing_id}")
            return

        score = score_listing(session, listing)
        _print_score(score)


def cmd_all(limit: int) -> None:
    with session_scope() as session:
        listings = session.scalars(
            select(Listing)
            .options(joinedload(Listing.location))
            .where(Listing.price_annual_ngn.isnot(None))
        ).all()

        print(f"Scoring {len(listings)} listings...\n")

        scored = [score_listing(session, l) for l in listings]

    scored = [s for s in scored if s.verdict != "insufficient_data"]
    print(f"{len(scored)} have a verdict (enough peers)\n")

    # Group by verdict category
    good_deals = [s for s in scored if s.verdict == "below_market"]
    good_deals.sort(key=lambda s: s.percentile or 100)

    suspicious = [s for s in scored if s.verdict.startswith("suspicious")]
    suspicious.sort(key=lambda s: abs(s.savings_pct_vs_median or 0), reverse=True)

    overpriced = [s for s in scored if s.verdict == "above_market"]
    overpriced.sort(key=lambda s: s.percentile or 0, reverse=True)

    half = max(1, limit // 2)

    print("=" * 100)
    print("🟢 BEST VALUE — genuinely below market")
    print("=" * 100)
    for score in good_deals[:half]:
        _print_score(score, compact=True)

    print()
    print("=" * 100)
    print("🟡🟠 SUSPICIOUS — prices far from median (verify before trusting)")
    print("=" * 100)
    for score in suspicious[:half]:
        _print_score(score, compact=True)

    print()
    print("=" * 100)
    print("🔴 OVERPRICED — top of market")
    print("=" * 100)
    for score in overpriced[:half]:
        _print_score(score, compact=True)


def cmd_query(location: str, bedrooms: int | None) -> None:
    with session_scope() as session:
        est = estimate_fair_value(session, location, bedrooms, purpose="rent")

    if est is None:
        print(f"No data for {bedrooms}-bed rentals in {location}")
        return

    print("=" * 60)
    print(f"Fair value estimate")
    print("=" * 60)
    print(f"  Location    : {est.location}")
    print(f"  Bedrooms    : {est.bedrooms if est.bedrooms is not None else 'unspecified'}")
    print(f"  Purpose     : {est.purpose}")
    print(f"  Peers       : {est.peer_count}")
    print()
    print(f"  Min         : ₦{est.min_price:>15,.0f}/yr")
    print(f"  25th pct    : ₦{est.q1:>15,.0f}/yr  ← fair range start")
    print(f"  Median      : ₦{est.median:>15,.0f}/yr")
    print(f"  75th pct    : ₦{est.q3:>15,.0f}/yr  ← fair range end")
    print(f"  Max         : ₦{est.max_price:>15,.0f}/yr")
    print()
    print(f"  Fair range  : ₦{est.q1:,.0f} – ₦{est.q3:,.0f}/yr")
    confidence = "high" if est.is_high_confidence else ("low" if est.has_verdict else "insufficient")
    print(f"  Confidence  : {confidence}")


def _print_score(score, compact: bool = False) -> None:
    emoji = EMOJI.get(score.verdict, "⚫")

    if compact:
        print(
            f"{emoji}  ₦{score.price:>14,.0f}  "
            f"{score.peer_group.bedrooms if score.peer_group.bedrooms is not None else '?':>3}-bed  "
            f"{score.peer_group.location:<20}  "
            f"p{score.percentile:>4.0f}  "
            f"{score.verdict_label}"
        )
        print(f"      {score.listing_title[:80]}")
    else:
        print(f"Listing #{score.listing_id}: {score.listing_title}")
        print(f"  Price       : ₦{score.price:,.0f}/yr")
        print(f"  Location    : {score.peer_group.location}")
        print(f"  Bedrooms    : {score.peer_group.bedrooms}")
        print(f"  Peers       : {score.peer_group.peer_count}")
        print(f"  Median      : ₦{score.peer_group.median:,.0f}/yr")
        print(f"  Fair range  : ₦{score.peer_group.q1:,.0f} – ₦{score.peer_group.q3:,.0f}/yr")
        if score.percentile is not None:
            print(f"  Percentile  : {score.percentile:.0f}")
        print(f"  Verdict     : {emoji} {score.verdict_label}")
        print(f"  Confidence  : {score.confidence}")
        if score.savings_vs_median is not None:
            sign = "+" if score.savings_vs_median > 0 else ""
            print(f"  Vs median   : {sign}₦{score.savings_vs_median:,.0f}/yr ({sign}{score.savings_pct_vs_median:.1f}%)")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--id", type=int, help="Score a single listing by DB id")
    parser.add_argument("--all", action="store_true", help="Score all listings")
    parser.add_argument("--limit", type=int, default=20, help="How many to show")
    parser.add_argument("--query", type=str, help="Query fair value by location")
    parser.add_argument("--bedrooms", type=int, help="Bedrooms for --query")
    args = parser.parse_args()

    if args.id:
        cmd_single(args.id)
    elif args.all:
        cmd_all(args.limit)
    elif args.query:
        cmd_query(args.query, args.bedrooms)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()