"""
Paystack integration: initiate transactions and verify payments.

Uses the raw Paystack REST API via httpx — no third-party wrapper needed.

The callback URL is resolved dynamically:
  1. APP_URL env var (set on Streamlit Cloud secrets)
  2. Falls back to http://localhost:8501 for local development
"""
from __future__ import annotations

import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Optional

import httpx
from sqlalchemy.orm import Session

from config.settings import settings
from src.models import User


logger = logging.getLogger(__name__)


PAYSTACK_BASE_URL = "https://api.paystack.co"

# Price of premium in NGN. Paystack requires amounts in KOBO
# (1 NGN = 100 kobo).
PREMIUM_PRICE_NGN = 2000
SUBSCRIPTION_DAYS = 30


class PaystackError(Exception):
    """Raised when the Paystack API returns an error."""


def _get_callback_url() -> str:
    """
    Return the URL Paystack should redirect users to after payment.

    Streamlit Cloud sets APP_URL via secrets. Locally, we default to
    localhost.
    """
    base = os.getenv("APP_URL", "http://localhost:8501").rstrip("/")
    return f"{base}/Payment_Callback"


def _headers() -> dict[str, str]:
    if not settings.paystack_secret_key:
        raise PaystackError(
            "PAYSTACK_SECRET_KEY is not set. Add it to .env."
        )
    return {
        "Authorization": f"Bearer {settings.paystack_secret_key}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def initiate_premium_payment(user: User) -> dict:
    """
    Start a Paystack transaction for the premium subscription.

    Returns:
      {
        "reference": "...",
        "authorization_url": "https://checkout.paystack.com/...",
        "access_code": "...",
      }
    """
    reference = f"NI-{user.id}-{secrets.token_hex(8)}"
    amount_kobo = PREMIUM_PRICE_NGN * 100
    callback_url = _get_callback_url()

    payload = {
        "email": user.email,
        "amount": amount_kobo,
        "currency": "NGN",
        "reference": reference,
        "callback_url": callback_url,
        "metadata": {
            "user_id": user.id,
            "purpose": "premium_subscription",
            "custom_fields": [
                {"display_name": "Plan", "variable_name": "plan", "value": "premium"},
                {
                    "display_name": "Duration",
                    "variable_name": "duration",
                    "value": f"{SUBSCRIPTION_DAYS} days",
                },
            ],
        },
    }

    logger.info("Initializing Paystack payment with callback: %s", callback_url)

    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.post(
                f"{PAYSTACK_BASE_URL}/transaction/initialize",
                headers=_headers(),
                json=payload,
            )
    except httpx.HTTPError as exc:
        logger.error("Paystack network error: %s", exc)
        raise PaystackError(f"Network error: {exc}") from exc

    if response.status_code >= 400:
        logger.error(
            "Paystack init failed (%d): %s", response.status_code, response.text[:300]
        )
        raise PaystackError(
            f"HTTP {response.status_code}: {response.text[:200]}"
        )

    try:
        data = response.json()
    except ValueError as exc:
        logger.error("Paystack returned non-JSON: %s", response.text[:300])
        raise PaystackError("Paystack returned an invalid response") from exc

    if not data.get("status"):
        message = data.get("message", "Unknown error")
        logger.error("Paystack rejected init: %s", message)
        raise PaystackError(message)

    body = data["data"]
    logger.info("Initiated payment %s for %s", reference, user.email)

    return {
        "reference": body["reference"],
        "authorization_url": body["authorization_url"],
        "access_code": body.get("access_code"),
    }


def verify_and_upgrade(session: Session, user: User, reference: str) -> dict:
    """
    Verify a Paystack transaction by reference and, if successful, upgrade
    the user to premium for SUBSCRIPTION_DAYS days.

    Returns {"success": bool, "message": str, "reference": str}.
    """
    try:
        with httpx.Client(timeout=30.0) as client:
            response = client.get(
                f"{PAYSTACK_BASE_URL}/transaction/verify/{reference}",
                headers=_headers(),
            )
    except httpx.HTTPError as exc:
        logger.error("Paystack verify network error: %s", exc)
        return {
            "success": False,
            "message": f"Network error: {exc}",
            "reference": reference,
        }

    if response.status_code >= 400:
        logger.error(
            "Paystack verify failed (%d): %s",
            response.status_code,
            response.text[:300],
        )
        return {
            "success": False,
            "message": f"Verification failed (HTTP {response.status_code})",
            "reference": reference,
        }

    try:
        data = response.json()
    except ValueError:
        return {
            "success": False,
            "message": "Paystack returned an invalid response",
            "reference": reference,
        }

    if not data.get("status"):
        return {
            "success": False,
            "message": data.get("message", "Verification rejected"),
            "reference": reference,
        }

    txn = data["data"]
    status = txn.get("status")

    if status != "success":
        logger.warning("Transaction %s not successful: %s", reference, status)
        return {
            "success": False,
            "message": f"Payment not successful (status: {status})",
            "reference": reference,
        }

    paid_amount_kobo = txn.get("amount", 0)
    if paid_amount_kobo < PREMIUM_PRICE_NGN * 100:
        logger.warning(
            "Amount mismatch on %s: paid %d kobo", reference, paid_amount_kobo
        )
        return {
            "success": False,
            "message": "Amount paid was less than expected",
            "reference": reference,
        }

    # Upgrade the user
    now = datetime.now(timezone.utc)
    user.plan = "premium"
    user.plan_expires_at = now + timedelta(days=SUBSCRIPTION_DAYS)
    session.commit()

    logger.info(
        "Upgraded %s to premium until %s", user.email, user.plan_expires_at
    )
    return {
        "success": True,
        "message": f"Upgraded to premium until {user.plan_expires_at.date()}",
        "reference": reference,
    }