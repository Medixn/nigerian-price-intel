"""
Check all watchlists for price changes since the user was last notified,
and send email alerts via Resend.

Usage:
    # Dry run — no emails sent, just logs what would happen
    python -m scripts.send_price_alerts

    # Actually send emails
    python -m scripts.send_price_alerts --send

    # Limit to a specific user (for debugging)
    python -m scripts.send_price_alerts --email user@example.com --send
"""
from __future__ import annotations

import argparse
import logging
import sys

from sqlalchemy import select

from src.db.session import session_scope
from src.models import AlertLog, Listing, User, Watchlist


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-7s  %(name)s  %(message)s",
    datefmt="%H:%M:%S",
    stream=sys.stdout,
)
logger = logging.getLogger("price_alerts")


def _send_notification(
    user: User,
    listing: Listing,
    old_price: float,
    new_price: float,
    send: bool,
) -> bool:
    """
    Send a price-change notification via the notifier service.

    Returns True if notification was sent (or would be sent in dry-run).
    """
    direction = "dropped" if new_price < old_price else "increased"
    pct = abs((new_price - old_price) / old_price) * 100 if old_price else 0

    print(
        f"  → {user.email}: {listing.title[:60]!r} {direction} "
        f"from ₦{old_price:,.0f} to ₦{new_price:,.0f} ({pct:.1f}%)"
    )

    if not send:
        print("     [DRY RUN — email not sent]")
        return True

    # Lazy import so dry-runs don't require the Resend package
    try:
        from src.services.notifier import send_price_alert
    except ImportError as exc:
        print(f"     [ERROR] Could not import notifier: {exc}")
        return False

    ok = send_price_alert(user, listing, old_price, new_price)
    if ok:
        print("     [email sent]")
    else:
        print("     [email FAILED — check logs]")
    return ok


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send price-change alerts to users watching listings."
    )
    parser.add_argument(
        "--send",
        action="store_true",
        help="Actually send emails via Resend (default is dry-run).",
    )
    parser.add_argument(
        "--email",
        type=str,
        help="Only process watchlists for this user email (for testing).",
    )
    args = parser.parse_args()

    send = args.send
    print(f"Mode: {'SEND' if send else 'DRY RUN'}\n")

    total_checked = 0
    total_changes = 0
    total_sent = 0
    total_failed = 0

    with session_scope() as session:
        # Load all watchlist entries joined with their listing and user.
        stmt = (
            select(Watchlist, Listing, User)
            .join(Listing, Listing.id == Watchlist.listing_id)
            .join(User, User.id == Watchlist.user_id)
        )
        if args.email:
            stmt = stmt.where(User.email == args.email.strip().lower())

        rows = session.execute(stmt).all()

        if not rows:
            print("No watchlist entries to check.")
            return 0

        print(f"Checking {len(rows)} watchlist entries...\n")

        for w, listing, user in rows:
            total_checked += 1

            current_price = listing.price_annual_ngn
            if current_price is None:
                continue

            last_notified = w.last_notified_price

            # First time we've seen this watchlist entry — set the baseline
            # and move on without alerting.
            if last_notified is None:
                if send:
                    w.last_notified_price = current_price
                print(
                    f"  [baseline] {user.email} watching "
                    f"{listing.source}:{listing.source_id} @ ₦{current_price:,.0f}"
                )
                continue

            # No change → nothing to do
            if last_notified == current_price:
                continue

            # Price changed — send alert
            total_changes += 1
            print(
                f"\n[change] {listing.source}:{listing.source_id} "
                f"({listing.title[:50]})"
            )

            sent = _send_notification(
                user, listing, last_notified, current_price, send
            )

            if sent:
                total_sent += 1
                if send:
                    session.add(AlertLog(
                        user_id=user.id,
                        listing_id=listing.id,
                        old_price=last_notified,
                        new_price=current_price,
                        channel="email",
                    ))
                    w.last_notified_price = current_price
            else:
                total_failed += 1

    print()
    print("=" * 60)
    print("Summary")
    print("=" * 60)
    print(f"  Watchlist entries checked : {total_checked}")
    print(f"  Price changes detected    : {total_changes}")
    if send:
        print(f"  Emails sent               : {total_sent}")
        print(f"  Emails failed             : {total_failed}")
    else:
        print(f"  (dry run — no emails sent)")

    return 0


if __name__ == "__main__":
    sys.exit(main())