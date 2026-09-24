"""
Copy all data from local SQLite to the cloud PostgreSQL database.

Reads DATABASE_URL from .streamlit/secrets.toml (or environment).
Uses .env's DATABASE_URL for the local SQLite source.

Usage:
    python -m scripts.migrate_to_cloud
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# ---------------------------------------------------------------
# Load the cloud URL from .streamlit/secrets.toml
# ---------------------------------------------------------------
try:
    import tomllib
except ImportError:
    tomllib = None

_secrets_path = Path(".streamlit/secrets.toml")
cloud_url: str | None = None

if _secrets_path.exists() and tomllib:
    with open(_secrets_path, "rb") as f:
        _secrets = tomllib.load(f)
    cloud_url = _secrets.get("DATABASE_URL")

if not cloud_url:
    # Fall back to environment
    cloud_url = os.getenv("DATABASE_URL")

if not cloud_url or not cloud_url.startswith("postgresql"):
    print("[ERROR] Cloud DATABASE_URL not found.")
    print("Expected it in .streamlit/secrets.toml or environment.")
    sys.exit(1)


# ---------------------------------------------------------------
# Local DB URL — read .env directly, ignore environment override
# ---------------------------------------------------------------
local_url: str | None = None

_env_path = Path(".env")
if _env_path.exists():
    for raw_line in _env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if line.startswith("DATABASE_URL="):
            local_url = line.split("=", 1)[1].strip()
            break

if not local_url:
    # Fallback: assume the standard SQLite path
    local_url = "sqlite:///data/listings.db"

if not local_url.startswith("sqlite"):
    print(f"[ERROR] Local DB in .env is not SQLite ({local_url[:40]}...).")
    print("Edit .env and set DATABASE_URL=sqlite:///data/listings.db")
    sys.exit(1)


# ---------------------------------------------------------------
# Now safe to import the models
# ---------------------------------------------------------------
from sqlalchemy import create_engine, select, text
from sqlalchemy.orm import Session

from src.models import (
    AlertLog,
    Listing,
    NormalizedLocation,
    PriceHistory,
    User,
    Watchlist,
)


def _truncate_cloud(engine) -> None:
    """Wipe any existing rows in the cloud DB so we have a clean slate."""
    with engine.begin() as conn:
        conn.execute(text(
            "TRUNCATE TABLE alert_log, watchlists, price_history, "
            "listings, users, locations RESTART IDENTITY CASCADE"
        ))
    print("Cleared existing cloud data.")


def main() -> int:
    print(f"Source (local) : {local_url}")
    print(f"Target (cloud) : {cloud_url[:40]}...\n")

    local_engine = create_engine(local_url, future=True)
    cloud_engine = create_engine(
        cloud_url, future=True, connect_args={"sslmode": "require"}
    )

    _truncate_cloud(cloud_engine)

    id_maps: dict[str, dict[int, int]] = {
        "locations": {},
        "users": {},
        "listings": {},
    }

    with Session(local_engine) as src, Session(cloud_engine) as dst:
        # --- Locations ---
        print("Copying locations...")
        for loc in src.scalars(select(NormalizedLocation)).all():
            new = NormalizedLocation(
                canonical_name=loc.canonical_name,
                state=loc.state,
                city=loc.city,
                area_type=loc.area_type,
                aliases=loc.aliases,
            )
            dst.add(new)
            dst.flush()
            id_maps["locations"][loc.id] = new.id
        dst.commit()
        print(f"  {len(id_maps['locations'])} locations copied")

        # --- Users ---
        print("Copying users...")
        for user in src.scalars(select(User)).all():
            new = User(
                email=user.email,
                password_hash=user.password_hash,
                display_name=user.display_name,
                plan=user.plan,
                plan_expires_at=user.plan_expires_at,
                listing_lookups_today=user.listing_lookups_today,
                lookups_reset_at=user.lookups_reset_at,
                is_active=user.is_active,
                created_at=user.created_at,
                last_login_at=user.last_login_at,
            )
            dst.add(new)
            dst.flush()
            id_maps["users"][user.id] = new.id
        dst.commit()
        print(f"  {len(id_maps['users'])} users copied")

        # --- Listings ---
        print("Copying listings...")
        for listing in src.scalars(select(Listing)).all():
            new = Listing(
                source=listing.source,
                source_id=listing.source_id,
                source_url=listing.source_url,
                title=listing.title,
                description=listing.description,
                purpose=listing.purpose,
                property_type=listing.property_type,
                bedrooms=listing.bedrooms,
                bathrooms=listing.bathrooms,
                toilets=listing.toilets,
                parking=listing.parking,
                location_id=id_maps["locations"].get(listing.location_id),
                raw_location=listing.raw_location,
                price_ngn=listing.price_ngn,
                price_period=listing.price_period,
                price_annual_ngn=listing.price_annual_ngn,
                price_monthly_ngn=listing.price_monthly_ngn,
                is_outlier=listing.is_outlier,
                outlier_reason=listing.outlier_reason,
                is_duplicate=listing.is_duplicate,
                listed_at=listing.listed_at,
                first_seen_at=listing.first_seen_at,
                last_seen_at=listing.last_seen_at,
            )
            dst.add(new)
            dst.flush()
            id_maps["listings"][listing.id] = new.id
        dst.commit()
        print(f"  {len(id_maps['listings'])} listings copied")

        # --- Price History ---
        print("Copying price history...")
        ph_count = 0
        for ph in src.scalars(select(PriceHistory)).all():
            new_listing_id = id_maps["listings"].get(ph.listing_id)
            if new_listing_id is None:
                continue
            dst.add(PriceHistory(
                listing_id=new_listing_id,
                price_ngn=ph.price_ngn,
                price_period=ph.price_period,
                recorded_at=ph.recorded_at,
                change_reason=ph.change_reason,
            ))
            ph_count += 1
        dst.commit()
        print(f"  {ph_count} price history rows copied")

        # --- Watchlists ---
        print("Copying watchlists...")
        w_count = 0
        for w in src.scalars(select(Watchlist)).all():
            new_user_id = id_maps["users"].get(w.user_id)
            new_listing_id = id_maps["listings"].get(w.listing_id)
            if new_user_id is None or new_listing_id is None:
                continue
            dst.add(Watchlist(
                user_id=new_user_id,
                listing_id=new_listing_id,
                created_at=w.created_at,
                last_notified_price=w.last_notified_price,
            ))
            w_count += 1
        dst.commit()
        print(f"  {w_count} watchlist rows copied")

        # --- Alert Log ---
        print("Copying alert log...")
        a_count = 0
        for a in src.scalars(select(AlertLog)).all():
            new_user_id = id_maps["users"].get(a.user_id)
            new_listing_id = id_maps["listings"].get(a.listing_id)
            if new_user_id is None or new_listing_id is None:
                continue
            dst.add(AlertLog(
                user_id=new_user_id,
                listing_id=new_listing_id,
                old_price=a.old_price,
                new_price=a.new_price,
                sent_at=a.sent_at,
                channel=a.channel,
            ))
            a_count += 1
        dst.commit()
        print(f"  {a_count} alert log rows copied")

    print("\nMigration complete.")
    return 0


if __name__ == "__main__":
    sys.exit(main())