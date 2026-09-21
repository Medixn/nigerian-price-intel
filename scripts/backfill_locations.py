"""
Backfill location_id and bulk flags on existing listings.

Walks every Listing row and applies:
  - location normalization (sets location_id)
  - bulk-listing detection (sets is_outlier / outlier_reason)

Run this once after adding the location normalizer to ingestion.

Usage:
    python -m scripts.backfill_locations
"""
from sqlalchemy import select

from src.db.session import session_scope
from src.models import Listing, NormalizedLocation
from src.services.ingestion import (
    _get_or_create_location,
    _looks_like_bulk,
    _normalizer,
)


def main() -> None:
    with session_scope() as session:
        listings = list(session.scalars(select(Listing)))
        print(f"Processing {len(listings)} listings...")

        located = 0
        bulk_flagged = 0

        for listing in listings:
            # --- Location normalization ---
            canonical = _normalizer.normalize(listing.raw_location)
            if canonical:
                loc_row = _get_or_create_location(session, canonical)
                if loc_row:
                    listing.location_id = loc_row.id
                    located += 1

            # --- Bulk detection ---
            if _looks_like_bulk(listing.title):
                listing.is_outlier = True
                listing.outlier_reason = "bulk listing (multiple units)"
                bulk_flagged += 1

        session.commit()

        # Report
        total = len(listings)
        print()
        print(f"  Total listings        : {total}")
        print(f"  With location_id set  : {located}")
        print(f"  Flagged as bulk       : {bulk_flagged}")

        # Show the canonical locations we ended up with
        print("\nCanonical locations created/found:")
        locs = session.scalars(
            select(NormalizedLocation).order_by(NormalizedLocation.canonical_name)
        ).all()
        for loc in locs:
            count = sum(1 for l in listings if l.location_id == loc.id)
            print(f"  {loc.canonical_name:<30} ({count} listings)")


if __name__ == "__main__":
    main()