"""NormalizedLocation — one row per canonical Nigerian location."""
from __future__ import annotations

from typing import Optional
from sqlalchemy import Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship
from .base import Base


class NormalizedLocation(Base):
    """
    A canonical location we've agreed on — e.g. "Lekki Phase 1".

    Multiple raw variants ("Lekki Phase I", "Lekki Ph 1", "Lekki phase1")
    all normalize to one row here.
    """
    __tablename__ = "locations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    canonical_name: Mapped[str] = mapped_column(String(200), unique=True, index=True)
    state: Mapped[Optional[str]] = mapped_column(String(100))
    city: Mapped[Optional[str]] = mapped_column(String(100))
    area_type: Mapped[Optional[str]] = mapped_column(String(50))  # neighborhood, estate, lga

    # JSON list of raw variants we've seen for this location
    aliases: Mapped[Optional[str]] = mapped_column(Text, nullable=True)

    listings: Mapped[list["Listing"]] = relationship(  # noqa: F821
        "Listing", back_populates="location"
    )

    def __repr__(self) -> str:
        return f"<Location {self.canonical_name!r}>"