"""
Abstract base class for all site scrapers.

Every site-specific scraper inherits from BaseScraper, which provides:
- HTTP client with sensible defaults (User-Agent, timeout, redirects)
- Polite rate limiting between requests
- Structured logging
- A consistent RawListing output format

Subclasses implement `scrape()` and yield RawListing objects.
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from typing import Iterator, Optional

import httpx
from pydantic import BaseModel, Field, HttpUrl


logger = logging.getLogger(__name__)


class RawListing(BaseModel):
    """
    What a scraper produces — before any cleaning or normalization.

    Every field is a string (or None). Parsing (prices, bedrooms, locations)
    happens later in the processing layer.
    """
    source: str = Field(..., description="Scraper name, e.g. 'npc'")
    source_id: str = Field(..., description="Stable ID within the source")
    source_url: str = Field(..., description="Absolute URL to the listing page")
    title: str
    description: Optional[str] = None
    raw_price: Optional[str] = None
    raw_location: Optional[str] = None
    raw_bedrooms: Optional[str] = None
    raw_bathrooms: Optional[str] = None
    raw_property_type: Optional[str] = None
    purpose: str = Field(..., description="'rent' or 'sale'")
    listed_at: Optional[str] = None
    scraped_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class BaseScraper(ABC):
    """Common behavior for all site scrapers."""

    source_name: str = "base"
    base_url: str = ""
    request_delay: float = 2.0  # seconds between requests — be polite

    def __init__(self, client: Optional[httpx.Client] = None):
        self.logger = logging.getLogger(f"scraper.{self.source_name}")
        self.client = client or httpx.Client(
            timeout=30.0,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/122.0.0.0 Safari/537.36"
                ),
                "Accept-Language": "en-NG,en;q=0.9",
            },
            follow_redirects=True,
        )

    def fetch(self, url: str) -> httpx.Response:
        """Fetch a URL with a polite delay and logging."""
        self.logger.info("Fetching %s", url)
        time.sleep(self.request_delay)
        response = self.client.get(url)
        response.raise_for_status()
        return response

    @abstractmethod
    def scrape(self, start_url: str, max_pages: int = 1) -> Iterator[RawListing]:
        """Yield RawListing objects for the given start URL."""
        raise NotImplementedError

    def close(self) -> None:
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()