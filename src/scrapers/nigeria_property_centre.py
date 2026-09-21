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
        """
        Scrape listings across pages, tolerating transient page failures.

        A single failed page is skipped. Only three consecutive failures
        cause us to stop, since that usually means the site is down or
        we've been rate-limited hard.
        """
        consecutive_failures = 0

        for page_num in range(1, max_pages + 1):
            page_url = start_url if page_num == 1 else f"{start_url}?page={page_num}"

            try:
                html = self.fetch(page_url).text
                consecutive_failures = 0  # reset counter on success
            except Exception as exc:
                consecutive_failures += 1
                self.logger.error(
                    "Failed to fetch %s (%d consecutive): %s",
                    page_url, consecutive_failures, exc,
                )
                if consecutive_failures >= 3:
                    self.logger.error("Too many consecutive failures; stopping.")
                    return
                continue  # skip this page, try the next

            listings = list(
                self.parse_html(html, purpose=self._purpose_from_url(start_url))
            )
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
                parsed["source_url"] = jld.get("url") or parsed["source_url"]
                parsed["title"] = jld.get("name") or parsed["title"]

                # Only accept NGN prices. Some listings are priced in USD;
                # those get skipped until we add currency conversion.
                if jld.get("price") and jld.get("currency", "NGN") == "NGN":
                    # Preserve period suffix from HTML (" /yr", " /month").
                    html_price = parsed.get("raw_price", "")
                    period_suffix = self._extract_period_suffix(html_price)
                    parsed["raw_price"] = f"₦{jld['price']}{period_suffix}"

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

    @staticmethod
    def _extract_period_suffix(price_text: str) -> str:
        """
        From a raw price string, pull out the period suffix if present.

        Examples:
            "₦15,500,000 /yr"      -> " /yr"
            "₦2,500,000 /month"    -> " /month"
            "₦38000000"            -> ""
        """
        if not price_text:
            return ""
        m = re.search(
            r"(/(?:yr|year|annum|month|mo)\b)", price_text, re.IGNORECASE
        )
        if m:
            return " " + m.group(1)
        return ""

    def _extract_price_text(self, card: Tag) -> str:
        """
        Find the price <span> and its period suffix.

        NPC puts the number in one span (e.g. "₦15,500,000") and the period
        suffix "/yr" or "/month" in a sibling span. We combine them so the
        price parser knows whether we're dealing with annual or monthly rent.

        Only accepts ₦-denominated prices. USD or other currencies return
        an empty string so they get skipped by the ingestion layer.
        """
        for span in card.find_all("span"):
            text = span.get_text(strip=True)
            if "₦" in text and any(c.isdigit() for c in text):
                period = ""
                sibling = span.find_next_sibling("span")
                if sibling:
                    sibling_text = sibling.get_text(strip=True)
                    if "/" in sibling_text or "per " in sibling_text.lower():
                        period = " " + sibling_text
                return (text + period).strip()
        return ""

    def _extract_by_icon(self, card: Tag, icon_id: str) -> str | None:
        """
        Find a `<use href="#i-bed">` and read the leading number from the
        text of its enclosing <span>.

        Returns the numeric part as a string, e.g. "2 beds" -> "2".

        Sanity-checks the result: Nigerian residential listings max out
        around 20 bedrooms. Anything larger is a parsing artefact (we
        grabbed a number from a description or a phone number) and is
        rejected.
        """
        use = card.find("use", href=f"#{icon_id}")
        if not use:
            return None

        parent = use.find_parent("span") or use.find_parent("div")
        if not parent:
            return None

        text = parent.get_text(" ", strip=True)
        m = re.match(r"(\d+)", text)
        if not m:
            return None

        value = int(m.group(1))
        if value < 1 or value > 20:
            return None
        return str(value)

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

        text_el = wrapper.select_one(".truncate")
        if text_el:
            return text_el.get_text(strip=True) or None

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
                if len(text) < 80:
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
        return None