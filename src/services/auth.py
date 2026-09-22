"""
Authentication and user management.

Uses bcrypt directly for password hashing (passlib is unmaintained
and incompatible with bcrypt 4.1+).

IMPORTANT: All mutating functions in this module commit explicitly.
Streamlit's st.rerun() raises an internal exception that can interrupt
the caller's context manager before it commits — so we never rely on
the caller to save our writes.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Optional

import bcrypt
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.models import User


logger = logging.getLogger(__name__)


# bcrypt only processes the first 72 bytes of a password. Anything longer
# is silently truncated. We truncate explicitly to avoid surprises.
_BCRYPT_MAX_BYTES = 72


def _prepare_password(password: str) -> bytes:
    """Encode to UTF-8 and truncate to 72 bytes (bcrypt's limit)."""
    encoded = password.encode("utf-8")
    return encoded[:_BCRYPT_MAX_BYTES]


def hash_password(plain: str) -> str:
    """
    Hash a plaintext password with bcrypt.

    Returns the hash as a UTF-8 string suitable for storing in the DB.
    """
    salt = bcrypt.gensalt(rounds=12)
    hashed = bcrypt.hashpw(_prepare_password(plain), salt)
    return hashed.decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Verify a plaintext password against a stored hash."""
    try:
        return bcrypt.checkpw(_prepare_password(plain), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


def create_user(
    session: Session,
    email: str,
    password: str,
    display_name: Optional[str] = None,
) -> User | None:
    """
    Create a new user. Returns None if the email already exists or is invalid.

    Commits the transaction explicitly.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return None

    existing = session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if existing is not None:
        return None

    user = User(
        email=email,
        password_hash=hash_password(password),
        display_name=display_name,
    )
    session.add(user)
    session.commit()
    session.refresh(user)  # ensure id, created_at, etc. are populated
    logger.info("Created user %s (id=%d)", email, user.id)
    return user


def authenticate(session: Session, email: str, password: str) -> Optional[User]:
    """
    Verify credentials. Returns the User on success, None on failure.
    Updates last_login_at and commits.
    """
    email = email.strip().lower()
    user = session.execute(
        select(User).where(User.email == email)
    ).scalar_one_or_none()
    if user is None:
        return None
    if not user.is_active:
        return None
    if not verify_password(password, user.password_hash):
        return None

    user.last_login_at = datetime.now(timezone.utc)
    session.commit()
    return user


def upgrade_to_premium(session: Session, user: User) -> None:
    """Manually upgrade a user to premium (real payments would call this)."""
    user.plan = "premium"
    session.commit()
    logger.info("Upgraded user %s to premium", user.email)


def consume_lookup_quota(session: Session, user: User) -> bool:
    """
    Called before a premium-gated action. Returns True if the user can proceed,
    False if they've hit their free-tier quota.

    Resets the daily counter when the calendar day has changed.
    Commits any state change explicitly.
    """
    if user.is_premium:
        return True

    now = datetime.now(timezone.utc)
    changed = False

    if user.lookups_reset_at.date() < now.date():
        user.listing_lookups_today = 0
        user.lookups_reset_at = now
        changed = True

    if user.listing_lookups_today >= 3:
        if changed:
            session.commit()
        return False

    user.listing_lookups_today += 1
    session.commit()
    return True