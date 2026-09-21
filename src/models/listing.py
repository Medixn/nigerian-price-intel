"""Listing and PriceHistory — the core entities of the platform."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Optional
from sqlalchemy import (
    Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Listing(Base):
    """A single property listing from one source."""
    __tablename__ = "listings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)

    # --- Identity ---
    source: Mapped[str] = mapped_column(String(50), nullable=False)
    source_id: Mapped[str] = mapped_column(String(100), nullable=False)
    source_url: Mapped[str] = mapped_column(String(500), nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    description: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    # --- Classification ---
    purpose: Mapped[str] = mapped_column(String(10), nullable=False)  # "rent" | "sale"
    property_type: Mapped[Optional[str]] = mapped_column(String(80), nullable=True)

    # --- Specs ---
    bedrooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    bathrooms: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    toilets: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    parking: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)

    # --- Location ---
    location_id: Mapped[Optional[int]] = mapped_column(
        ForeignKey("locations.id"), nullable=True, index=True
    )
    raw_location: Mapped[Optional[str]] = mapped_column(String(300), nullable=True)
    location: Mapped[Optional["NormalizedLocation"]] = relationship(  # noqa: F821
        "NormalizedLocation", back_populates="listings"
    )

    # --- Price (normalized) ---
    price_ngn: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_period: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    price_annual_ngn: Mapped[Optional[float]] = mapped_column(Float, nullable=True)
    price_monthly_ngn: Mapped[Optional[float]] = mapped_column(Float, nullable=True)

    # --- Quality flags ---
    is_outlier: Mapped[bool] = mapped_column(Boolean, default=False)
    outlier_reason: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    is_duplicate: Mapped[bool] = mapped_column(Boolean, default=False)

    # --- Timestamps ---
    listed_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
    first_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    last_seen_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    price_history: Mapped[list["PriceHistory"]] = relationship(
        "PriceHistory", back_populates="listing",
        order_by="PriceHistory.recorded_at",
        cascade="all, delete-orphan",
    )

    __table_args__ = (
        Index("ix_listing_source_sourceid", "source", "source_id", unique=True),
        Index("ix_listing_purpose_bedrooms", "purpose", "bedrooms"),
    )

    def __repr__(self) -> str:
        return f"<Listing {self.source}:{self.source_id} {self.title[:40]!r}>"


class PriceHistory(Base):
    """Every time we observe a listing's price, we record it here."""
    __tablename__ = "price_history"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    listing_id: Mapped[int] = mapped_column(
        ForeignKey("listings.id"), nullable=False, index=True
    )
    listing: Mapped[Listing] = relationship("Listing", back_populates="price_history")

    price_ngn: Mapped[float] = mapped_column(Float, nullable=False)
    price_period: Mapped[Optional[str]] = mapped_column(String(20), nullable=True)
    recorded_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    change_reason: Mapped[str] = mapped_column(String(50), nullable=False)  # initial | price_drop | price_increase

    def __repr__(self) -> str:
        return f"<PriceHistory listing={self.listing_id} {self.price_ngn:.0f} {self.change_reason}>"