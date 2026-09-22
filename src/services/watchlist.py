"""Watchlist and alert operations."""
from __future__ import annotations

import logging

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import Listing, User, Watchlist


logger = logging.getLogger(__name__)


def add_to_watchlist(session: Session, user: User, listing_id: int) -> Watchlist | None:
    """Add a listing to the user's watchlist. Idempotent."""
    existing = session.execute(
        select(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.listing_id == listing_id,
        )
    ).scalar_one_or_none()
    if existing is not None:
        return existing

    w = Watchlist(user_id=user.id, listing_id=listing_id)
    session.add(w)
    session.flush()
    return w


def remove_from_watchlist(session: Session, user: User, listing_id: int) -> bool:
    """Remove a listing from the watchlist. Returns True if it existed."""
    existing = session.execute(
        select(Watchlist).where(
            Watchlist.user_id == user.id,
            Watchlist.listing_id == listing_id,
        )
    ).scalar_one_or_none()
    if existing is None:
        return False
    session.delete(existing)
    return True


def is_watched(session: Session, user: User, listing_id: int) -> bool:
    """Check if a listing is already on the user's watchlist."""
    existing = session.execute(
        select(Watchlist.id).where(
            Watchlist.user_id == user.id,
            Watchlist.listing_id == listing_id,
        )
    ).scalar_one_or_none()
    return existing is not None


def list_watchlist(session: Session, user: User) -> list[tuple[Watchlist, Listing]]:
    """Get the user's watchlist, joined with listing details."""
    rows = session.execute(
        select(Watchlist, Listing)
        .join(Listing, Listing.id == Watchlist.listing_id)
        .where(Watchlist.user_id == user.id)
        .order_by(Watchlist.created_at.desc())
    ).all()
    return [(w, l) for w, l in rows]