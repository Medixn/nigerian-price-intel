"""
Run the NPC scraper against our saved sample HTML and persist listings
to the database.

Usage:
    python -m scripts.ingest_npc_sample
"""
from pathlib import Path

from src.db.session import session_scope
from src.scrapers.nigeria_property_centre import NigeriaPropertyCentreScraper
from src.services.ingestion import ingest_batch


SAMPLE = Path("data/raw/npc_sample.html")


def main() -> None:
    if not SAMPLE.exists():
        print(f"[ERROR] Sample file not found: {SAMPLE}")
        return

    html = SAMPLE.read_text(encoding="utf-8")
    print(f"Loaded {len(html):,} characters from {SAMPLE}\n")

    scraper = NigeriaPropertyCentreScraper()
    try:
        listings = list(scraper.parse_html(html, purpose="rent"))
    finally:
        scraper.close()

    print(f"Parsed {len(listings)} raw listings\n")

    with session_scope() as session:
        stats = ingest_batch(session, listings)

    print("Ingestion summary:")
    print(f"  Inserted : {stats['inserted']}")
    print(f"  Updated  : {stats['updated']}")
    print(f"  Skipped  : {stats['skipped']}")


if __name__ == "__main__":
    main()