# Nigerian Real Estate Price Intelligence

A price-intelligence platform for the Nigerian property market, focused on
clean data, historical trends, fair-value estimates, and price-drop alerts.

## Status

Working end-to-end pipeline:
- Tested price parser (10/10 cases, handles Nigerian formats like "₦2.5m p.a")
- Nigeria Property Centre scraper — 21 listings per page
- SQLAlchemy models (Listing, PriceHistory, NormalizedLocation)
- SQLite persistence with idempotent upsert
- CLI tools for init, ingest, and inspection

## Setup

    python -m venv .venv
    .venv\Scripts\Activate.ps1     # Windows
    source .venv/bin/activate      # Mac/Linux
    pip install -r requirements.txt

## Commands

    # Initialize the database (creates data/listings.db)
    python -m scripts.init_db

    # Ingest the saved NPC sample page
    python -m scripts.ingest_npc_sample

    # Query the database for summary statistics
    python -m scripts.inspect_db

    # Run the price parser tests
    python -m tests.test_price_parser

## Structure

- `src/scrapers/`      — one module per site, all inheriting from BaseScraper
- `src/processing/`    — data cleaning and intelligence (price parser, etc.)
- `src/models/`        — SQLAlchemy schema
- `src/services/`      — business logic (ingestion, later: alerts, intelligence)
- `src/db/`            — database engine and session factory
- `scripts/`           — CLI tools (init, ingest, inspect, run)
- `tests/`             — test suite
- `data/`              — SQLite DB, raw HTML snapshots (gitignored)

## Roadmap

- [x] Week 1 — Foundation, config, price parser
- [x] Week 2 — NPC scraper + database + ingestion
- [ ] Week 3 — Data quality: location normalizer, dedup, outlier detection
- [ ] Week 4 — Intelligence: fair value, trends, yield
- [ ] Week 5 — Streamlit dashboard
- [ ] Week 6 — Scheduling, alerts, monetization