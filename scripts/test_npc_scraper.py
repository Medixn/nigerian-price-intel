"""
Run the NPC scraper against a saved HTML file (no network calls).

Usage:
    python -m scripts.test_npc_scraper
"""
from pathlib import Path

from src.scrapers.nigeria_property_centre import NigeriaPropertyCentreScraper


SAMPLE = Path("data/raw/npc_sample.html")


def main() -> None:
    if not SAMPLE.exists():
        print(f"[ERROR] Sample file not found: {SAMPLE}")
        print("Save a page first with the snapshot command.")
        return

    html = SAMPLE.read_text(encoding="utf-8")
    print(f"Loaded {len(html):,} characters from {SAMPLE}\n")

    scraper = NigeriaPropertyCentreScraper()
    try:
        listings = list(scraper.parse_html(
            html,
            purpose="rent",
        ))
    finally:
        scraper.close()

    print(f"Parsed {len(listings)} listings\n")
    print("=" * 100)

    for i, listing in enumerate(listings, 1):
        print(f"\n#{i}")
        print(f"  ID       : {listing.source_id}")
        print(f"  Title    : {listing.title[:70]}")
        print(f"  Price    : {listing.raw_price}")
        print(f"  Location : {listing.raw_location}")
        print(f"  Type     : {listing.raw_property_type}")
        print(f"  Beds     : {listing.raw_bedrooms}")
        print(f"  Baths    : {listing.raw_bathrooms}")
        print(f"  URL      : {listing.source_url}")

    print("\n" + "=" * 100)
    print(f"\nTotal: {len(listings)} listings")


if __name__ == "__main__":
    main()