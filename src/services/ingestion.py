"""
Ingestion service: takes RawListing objects and persists them.

Responsibilities:
  - Parse raw price -> numeric NGN + period
  - Convert to monthly / annual equivalents
  - Detect price changes vs. existing records
  - Update last_seen_at on re-scrape
  - Insert new listings
  - Record every price observation in price_history
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterable

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Listing, PriceHistory
from src.processing.price_parser import parse_price, to_monthly, to_annual
from src.scrapers.base import RawListing


logger = logging.getLogger(__name__)


def _parse_int(value: str | None) -> int | None:
    """Safely convert a string to int, returning None on any failure."""
    if not value:
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None


def ingest_listing(session: Session, raw: RawListing) -> Listing | None:
    """
    Insert or update a single listing. Returns the persisted Listing,
    or None if the raw data was unusable (e.g. no valid price).
    """
    # Parse price
    price_ngn, price_period = parse_price(raw.raw_price or "")
    if price_ngn is None:
        logger.debug("Skipping listing %s: no valid NGN price", raw.source_id)
        return None

    price_monthly = to_monthly(price_ngn, price_period)
    price_annual = to_annual(price_ngn, price_period)

    # Look for an existing record
    existing = session.execute(
        select(Listing).where(
            Listing.source == raw.source,
            Listing.source_id == raw.source_id,
        )
    ).scalar_one_or_none()

    if existing:
        # Detect price change
        old_price = existing.price_ngn
        if old_price is not None and price_ngn != old_price:
            reason = "price_drop" if price_ngn < old_price else "price_increase"
            session.add(PriceHistory(
                listing_id=existing.id,
                price_ngn=price_ngn,
                price_period=price_period,
                change_reason=reason,
            ))
            logger.info(
                "Price change on %s:%s - %.0f -> %.0f (%s)",
                raw.source, raw.source_id, old_price, price_ngn, reason,
            )

        # Update fields
        existing.price_ngn = price_ngn
        existing.price_period = price_period
        existing.price_monthly_ngn = price_monthly
        existing.price_annual_ngn = price_annual
        existing.title = raw.title
        existing.raw_location = raw.raw_location
        existing.bedrooms = _parse_int(raw.raw_bedrooms)
        existing.bathrooms = _parse_int(raw.raw_bathrooms)
        existing.last_seen_at = datetime.now(timezone.utc)
        return existing

    # New listing
    listing = Listing(
        source=raw.source,
        source_id=raw.source_id,
        source_url=raw.source_url,
        title=raw.title,
        description=raw.description,
        purpose=raw.purpose,
        property_type=raw.raw_property_type,
        bedrooms=_parse_int(raw.raw_bedrooms),
        bathrooms=_parse_int(raw.raw_bathrooms),
        raw_location=raw.raw_location,
        price_ngn=price_ngn,
        price_period=price_period,
        price_monthly_ngn=price_monthly,
        price_annual_ngn=price_annual,
    )
    session.add(listing)
    session.flush()  # assign an id

    session.add(PriceHistory(
        listing_id=listing.id,
        price_ngn=price_ngn,
        price_period=price_period,
        change_reason="initial",
    ))

    return listing


def ingest_batch(session: Session, raws: Iterable[RawListing]) -> dict:
    """
    Insert a batch of RawListing objects.

    Returns {"inserted": N, "updated": M, "skipped": K}.
    """
    stats = {"inserted": 0, "updated": 0, "skipped": 0}

    for raw in raws:
        try:
            # Peek to know if it's new
            exists = session.execute(
                select(Listing.id).where(
                    Listing.source == raw.source,
                    Listing.source_id == raw.source_id,
                )
            ).scalar_one_or_none()

            result = ingest_listing(session, raw)
            if result is None:
                stats["skipped"] += 1
            elif exists:
                stats["updated"] += 1
            else:
                stats["inserted"] += 1

        except Exception as exc:
            logger.error("Failed to ingest %s:%s - %s", raw.source, raw.source_id, exc)
            stats["skipped"] += 1

    return stats