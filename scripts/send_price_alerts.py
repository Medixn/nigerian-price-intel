"""
Check all watchlists for price changes since the user was last notified,
and print (or email) alerts.

For the MVP we just log to console. Real sending happens via the
_notifier module.

Usage:
    python -m scripts.send_price_alerts --dry-run
"""
from __future__ import annotations

import argparse
import logging

from sqlalchemy import select

from src.db.session import session_scope
from src.models import AlertLog, Listing, User, Watchlist


logger = logging.getLogger("price_alerts")


def _send_notification(user: User, listing: Listing, old: float, new: float) -> bool:
    """
    Stub for the actual notification. Real version would send email,
    Telegram, or WhatsApp.

    Returns True if notification was sent successfully.
    """
    direction = "dropped" if new < old else "increased"
    pct = abs((new - old) / old) * 100 if old else 0
    print(
        f"  → Notify {user.email}: {listing.title[:60]!r} {direction} "
        f"from ₦{old:,.0f} to ₦{new:,.0f} ({pct:.1f}%)"
    )
    return True


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Don't record alerts")
    args = parser.parse_args()

    total_checked = 0
    total_sent = 0

    with session_scope() as session:
        # For each watchlist entry, compare the listing's current price
        # against what we last notified the user about.
        rows = session.execute(
            select(Watchlist, Listing, User)
            .join(Listing, Listing.id == Watchlist.listing_id)
            .join(User, User.id == Watchlist.user_id)
        ).all()

        for w, listing, user in rows:
            total_checked += 1

            current_price = listing.price_annual_ngn
            last_notified = w.last_notified_price

            # Never notified before → set baseline, don't alert
            if last_notified is None:
                if not args.dry_run:
                    w.last_notified_price = current_price
                continue

            # No change → nothing to do
            if last_notified == current_price:
                continue

            # Price changed → send alert
            print(f"Change on {listing.source}:{listing.source_id}")
            sent = _send_notification(user, listing, last_notified, current_price)
            if sent:
                total_sent += 1
                if not args.dry_run:
                    session.add(AlertLog(
                        user_id=user.id,
                        listing_id=listing.id,
                        old_price=last_notified,
                        new_price=current_price,
                        channel="console",
                    ))
                    w.last_notified_price = current_price

    print()
    print(f"Checked {total_checked} watchlist entries, sent {total_sent} alerts.")


if __name__ == "__main__":
    main()