"""
Run a scraper against a live URL and ingest the results into the DB.

Usage:
    python -m scripts.run_scraper --source npc --url "https://nigeriapropertycentre.com/for-rent/flats-apartments/lagos" --pages 10
"""
from __future__ import annotations

import argparse
import logging
import sys
from time import perf_counter

from src.db.session import session_scope
from src.scrapers.nigeria_property_centre import NigeriaPropertyCentreScraper
from src.services.ingestion import ingest_batch


# Available scrapers, keyed by CLI name
SCRAPERS = {
    "npc": NigeriaPropertyCentreScraper,
}


def configure_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s  %(levelname)-7s  %(name)-20s  %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stdout,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run a live scraper and ingest into the DB.")
    parser.add_argument("--source", required=True, choices=list(SCRAPERS.keys()),
                        help="Which scraper to run")
    parser.add_argument("--url", required=True,
                        help="Starting URL (the scraper paginates from here)")
    parser.add_argument("--pages", type=int, default=1,
                        help="Max pages to scrape (default: 1)")
    parser.add_argument("--delay", type=float, default=None,
                        help="Override seconds between requests (default: 2.0)")
    parser.add_argument("--verbose", "-v", action="store_true",
                        help="Debug-level logging")
    args = parser.parse_args()

    configure_logging(args.verbose)
    log = logging.getLogger("run_scraper")

    scraper_cls = SCRAPERS[args.source]
    scraper = scraper_cls()

    if args.delay is not None:
        scraper.request_delay = args.delay

    log.info("Starting scraper=%s url=%s pages=%d delay=%.1fs",
             args.source, args.url, args.pages, scraper.request_delay)

    started = perf_counter()
    total_seen = 0
    total_stats = {"inserted": 0, "updated": 0, "skipped": 0}

    try:
        # Stream listings page by page, ingesting as we go so we don't
        # buffer hundreds of RawListings in memory.
        for i, listing in enumerate(scraper.scrape(args.url, max_pages=args.pages), 1):
            total_seen = i
            with session_scope() as session:
                stats = ingest_batch(session, [listing])
            for key in total_stats:
                total_stats[key] += stats[key]

            if i % 25 == 0:
                log.info("Progress: %d listings processed", i)

    except KeyboardInterrupt:
        log.warning("Interrupted by user")
    finally:
        scraper.close()

    elapsed = perf_counter() - started

    print()
    print("=" * 60)
    print(f"Scrape complete in {elapsed:.1f}s")
    print(f"  Listings seen : {total_seen}")
    print(f"  Inserted      : {total_stats['inserted']}")
    print(f"  Updated       : {total_stats['updated']}")
    print(f"  Skipped       : {total_stats['skipped']}")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())