"""
Notification service — sends emails via Resend.

Used by send_price_alerts to notify users when a watched listing's
price changes.
"""
from __future__ import annotations

import logging
from typing import Optional

import resend

from config.settings import settings
from src.models import Listing, User


logger = logging.getLogger(__name__)


# Initialize Resend once at import time.
if settings.resend_api_key:
    resend.api_key = settings.resend_api_key


def _format_ngn(value: float) -> str:
    if value >= 1_000_000_000:
        return f"₦{value / 1_000_000_000:.2f}B"
    if value >= 1_000_000:
        return f"₦{value / 1_000_000:.1f}M"
    if value >= 1_000:
        return f"₦{value / 1_000:.0f}K"
    return f"₦{value:,.0f}"


def _email_html(user: User, listing: Listing, old_price: float, new_price: float) -> str:
    """Render the alert email as HTML."""
    direction = "dropped" if new_price < old_price else "increased"
    arrow = "↓" if new_price < old_price else "↑"
    color = "#2CA02C" if new_price < old_price else "#D62728"
    pct = abs((new_price - old_price) / old_price) * 100 if old_price else 0

    return f"""
    <!doctype html>
    <html>
    <body style="font-family: -apple-system, Helvetica, Arial, sans-serif;
                 max-width: 600px; margin: 0 auto; padding: 24px; color: #222;">
        <h2 style="margin: 0 0 16px; font-size: 20px;">Price alert: {listing.title[:80]}</h2>

        <p style="font-size: 15px; line-height: 1.6; color: #555;">
            A listing you're watching on Nigerian Property Intelligence
            just <strong>{direction}</strong> in price.
        </p>

        <div style="background: #f5f5f5; border-radius: 8px; padding: 16px;
                    margin: 20px 0; text-align: center;">
            <div style="font-size: 13px; color: #888; margin-bottom: 6px;">
                New price
            </div>
            <div style="font-size: 32px; font-weight: 700; color: {color};">
                {arrow} {_format_ngn(new_price)}
            </div>
            <div style="font-size: 13px; color: #888; margin-top: 8px;">
                {_format_ngn(old_price)} → {_format_ngn(new_price)}
                ({pct:.1f}% change)
            </div>
        </div>

        <p style="font-size: 15px; line-height: 1.6;">
            <strong>Location:</strong> {listing.raw_location or "—"}<br>
            <strong>Bedrooms:</strong> {listing.bedrooms or "—"}<br>
            <strong>Type:</strong> {listing.property_type or "—"}
        </p>

        <p style="margin: 24px 0;">
            <a href="{listing.source_url}"
               style="display: inline-block; padding: 12px 24px;
                      background: #4C78A8; color: white; text-decoration: none;
                      border-radius: 6px; font-weight: 600;">
                View listing →
            </a>
        </p>

        <hr style="border: none; border-top: 1px solid #eee; margin: 32px 0;">

        <p style="font-size: 12px; color: #999; line-height: 1.5;">
            You're receiving this because you're watching this listing on
            Nigerian Property Intelligence.<br>
            To stop receiving alerts, remove it from your watchlist
            (Account → Your Watchlist).
        </p>
    </body>
    </html>
    """


def send_price_alert(
    user: User,
    listing: Listing,
    old_price: float,
    new_price: float,
) -> bool:
    """
    Send a price-change email. Returns True on success.

    Safe to call even when RESEND_API_KEY isn't set (logs and returns False).
    """
    if not settings.resend_api_key:
        logger.warning(
            "RESEND_API_KEY not set — skipping email to %s", user.email
        )
        return False

    subject = (
        f"Price drop: {_format_ngn(old_price)} → {_format_ngn(new_price)} "
        f"({listing.title[:50]})"
        if new_price < old_price
        else f"Price increase: {_format_ngn(old_price)} → {_format_ngn(new_price)}"
    )

    try:
        response = resend.Emails.send({
            "from": f"Nigerian Property Intelligence <{settings.alert_from_email}>",
            "to": [user.email],
            "subject": subject,
            "html": _email_html(user, listing, old_price, new_price),
        })
        logger.info("Sent alert to %s (id=%s)", user.email, response.get("id"))
        return True
    except Exception as exc:
        logger.error("Failed to send alert to %s: %s", user.email, exc)
        return False