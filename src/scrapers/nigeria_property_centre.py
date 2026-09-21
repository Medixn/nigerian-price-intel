"""
Scraper for Nigeria Property Centre (nigeriapropertycentre.com).

Strategy:
  1. Parse the JSON-LD <script type="application/ld+json"> block for
     reliable URL / title / price data — NPC publishes every listing there.
  2. Parse the HTML <article> cards for enrichment: bedrooms, bathrooms,
     location, agent, photo count.

The two are matched by source_id (the numeric ID in the listing URL).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from typing import Iterator
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

from .base import BaseScraper, RawListing


NPC_BASE = "https://nigeriapropertycentre.com"


class NigeriaPropertyCentreScraper(BaseScraper):
    source_name = "npc"
    base_url = NPC_BASE

    def scrape(self, start_url: str, max_pages: int = 1) -> Iterator[RawListing]:
        """Scrape listings across pages."""
        for page_num in range(1, max_pages + 1):
            page_url = start_url if page_num == 1 else f"{start_url}?page={page_num}"
            try:
                html = self.fetch(page_url).text
            except Exception as exc:
                self.logger.error("Failed to fetch %s: %s", page_url, exc)
                return

            listings = list(self.parse_html(html, purpose=self._purpose_from_url(start_url)))
            self.logger.info("Page %d: parsed %d listings", page_num, len(listings))

            if not listings:
                self.logger.info("No listings found on page %d; stopping.", page_num)
                return

            yield from listings

    # ----------------------------------------------------------------
    # Parsing — pure function, testable without network
    # ----------------------------------------------------------------
    def parse_html(self, html: str, purpose: str) -> Iterator[RawListing]:
        soup = BeautifulSoup(html, "html.parser")

        # Step 1: index JSON-LD listings by source_id
        json_ld_index = self._index_json_ld(soup)

        # Step 2: walk each article card
        seen_ids: set[str] = set()
        for card in soup.select("article"):
            parsed = self._parse_card(card, purpose=purpose)
            if parsed is None:
                continue

            source_id = parsed["source_id"]
            if source_id in seen_ids:
                continue
            seen_ids.add(source_id)

            # Merge JSON-LD data if available (more reliable than HTML)
            jld = json_ld_index.get(source_id, {})
            if jld:
                # JSON-LD URL is often more complete (absolute)
                parsed["source_url"] = jld.get("url") or parsed["source_url"]
                parsed["title"] = jld.get("name") or parsed["title"]

                # Only accept NGN prices. Some listings are priced in USD;
                # those get skipped until we add currency conversion.
                if jld.get("price") and jld.get("currency", "NGN") == "NGN":
                    parsed["raw_price"] = f"₦{jld['price']}"

            yield RawListing(
                source=self.source_name,
                source_id=source_id,
                source_url=urljoin(NPC_BASE, parsed["source_url"]),
                title=parsed.get("title") or "",
                description=None,
                raw_price=parsed.get("raw_price") or None,
                raw_location=parsed.get("raw_location") or None,
                raw_bedrooms=parsed.get("bedrooms") or None,
                raw_bathrooms=parsed.get("bathrooms") or None,
                raw_property_type=parsed.get("property_type") or None,
                purpose=purpose,
                listed_at=parsed.get("listed_at"),
                scraped_at=datetime.now(timezone.utc).isoformat(),
            )

    # ----------------------------------------------------------------
    # JSON-LD extraction
    # ----------------------------------------------------------------
    @staticmethod
    def _index_json_ld(soup: BeautifulSoup) -> dict[str, dict]:
        """
        Find the ItemList JSON-LD block and index its listings by source_id.

        Returns {source_id: {"url", "name", "price", "currency"}}
        """
        index: dict[str, dict] = {}

        for script in soup.find_all("script", type="application/ld+json"):
            try:
                data = json.loads(script.string or "")
            except (json.JSONDecodeError, TypeError):
                continue

            if data.get("@type") != "ItemList":
                continue

            for item in data.get("itemListElement", []):
                url = item.get("url", "")
                source_id = NigeriaPropertyCentreScraper._extract_id_from_url(url)
                if not source_id:
                    continue

                offer = item.get("offers") or {}
                index[source_id] = {
                    "url": url,
                    "name": item.get("name"),
                    "price": offer.get("price"),
                    "currency": offer.get("priceCurrency", "NGN"),
                }

        return index

    # ----------------------------------------------------------------
    # HTML card extraction
    # ----------------------------------------------------------------
    def _parse_card(self, card: Tag, purpose: str) -> dict | None:
        """Extract raw fields from a single <article> card."""
        # Find the stretched <a> link with the listing URL
        link = card.select_one('a.absolute.inset-0[href]')
        if not link:
            # Fallback: any <a> with a listing-style URL
            link = card.find("a", href=re.compile(r"/\d{5,}-"))
        if not link:
            return None

        href = link.get("href", "")
        source_id = self._extract_id_from_url(href)
        if not source_id:
            return None

        result: dict = {
            "source_id": source_id,
            "source_url": href,
            "title": link.get("aria-label") or self._text(card.select_one("h3")),
            "raw_price": self._extract_price_text(card),
            "raw_location": self._extract_location(card),
            "bedrooms": self._extract_by_icon(card, "i-bed"),
            "bathrooms": self._extract_by_icon(card, "i-bath"),
            "property_type": self._extract_property_type(card),
        }

        # "Added today" / "Added N days ago" pill
        listed_at = self._extract_listed_at(card)
        if listed_at:
            result["listed_at"] = listed_at

        return result

    # ----------------------------------------------------------------
    # Helpers
    # ----------------------------------------------------------------
    @staticmethod
    def _extract_id_from_url(url: str) -> str | None:
        """Pull the numeric listing ID out of a URL like .../3606441-slug."""
        if not url:
            return None
        m = re.search(r"/(\d{5,})-", url)
        return m.group(1) if m else None

    @staticmethod
    def _purpose_from_url(url: str) -> str:
        return "sale" if "/for-sale/" in url else "rent"

    @staticmethod
    def _text(el: Tag | None) -> str:
        return el.get_text(" ", strip=True) if el else ""

    def _extract_price_text(self, card: Tag) -> str:
        """
        Find the price <span>.

        Only accepts ₦-denominated prices. USD or other currencies
        return an empty string so they get skipped.
        """
        for span in card.find_all("span"):
            text = span.get_text(strip=True)
            if "₦" in text and any(c.isdigit() for c in text):
                return text
        return ""

    def _extract_by_icon(self, card: Tag, icon_id: str) -> str | None:
        """
        Find a `<use href="#i-bed">` and read the leading number from the
        text of its enclosing <span>.

        Returns the numeric part as a string, e.g. "2 beds" → "2".
        """
        use = card.find("use", href=f"#{icon_id}")
        if not use:
            return None

        # Walk up to the enclosing <span> or <div> that has text
        parent = use.find_parent("span") or use.find_parent("div")
        if not parent:
            return None

        text = parent.get_text(" ", strip=True)
        # Extract leading number: "2 beds" → "2", "1 bath" → "1", "3 toilets" → "3"
        m = re.match(r"(\d+)", text)
        return m.group(1) if m else None

    def _extract_location(self, card: Tag) -> str | None:
        """
        Extract the location string from a card.

        NPC puts the location inside a <span class="truncate"> right after
        a map-pin icon. We find the icon, walk to its parent <span>, then
        read the .truncate child. Falls back to the wrapper's full text.
        """
        use = card.find("use", href="#i-map-pin")
        if not use:
            return None

        wrapper = use.find_parent("span")
        if not wrapper:
            return None

        # The actual text is inside a child with class "truncate"
        text_el = wrapper.select_one(".truncate")
        if text_el:
            return text_el.get_text(strip=True) or None

        # Fallback: entire wrapper text (may include the "Added today" badge)
        text = wrapper.get_text(" ", strip=True)
        return text or None

    def _extract_property_type(self, card: Tag) -> str | None:
        """
        Property type text is in the <p> immediately after the price block,
        e.g. 'Flat / apartment for rent', 'Mini flat (room and parlour) for rent'.
        """
        for p in card.find_all("p"):
            text = p.get_text(" ", strip=True)
            if " for rent" in text.lower() or " for sale" in text.lower():
                if len(text) < 80:  # avoid matching descriptions
                    return text
        return None

    def _extract_listed_at(self, card: Tag) -> str | None:
        """
        Look for a calendar-icon span with text like "Added today" or
        "Added 3 days ago". Returns ISO date string if we can determine
        one, else None.
        """
        use = card.find("use", href="#i-calendar")
        if not use:
            return None

        parent = use.find_parent("span")
        if not parent:
            return None

        text = parent.get_text(" ", strip=True).lower()
        if "today" in text:
            return datetime.now(timezone.utc).isoformat()
        # "N days ago" parsing left for a later pass
        return None