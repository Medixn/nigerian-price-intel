"""
Location normalization: collapse raw location strings into canonical names.

The raw_location field we capture from NPC is a comma-separated path like:
    "3rd Avenue, Banana Island, Ikoyi, Lagos"
    "Lekki Phase 1, Lekki, Lagos"

We split on commas, drop the state, then try each remaining part against
a curated list of canonical locations in config/locations.yaml.

Candidates are tried in ORIGINAL ORDER (left to right). NPC lists the
most specific subarea first, so "Oniru, Victoria Island, Lagos" should
resolve to Oniru, not Victoria Island.

Uses rapidfuzz for fuzzy matching to handle typos and variants.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml
from rapidfuzz import fuzz, process

logger = logging.getLogger(__name__)


# Match threshold for fuzzy comparison (0-100). Higher = stricter.
FUZZY_THRESHOLD = 88

# Path to the locations YAML (relative to project root)
_DEFAULT_YAML = Path(__file__).resolve().parent.parent.parent / "config" / "locations.yaml"


class LocationNormalizer:
    """Map raw location strings to canonical location names."""

    def __init__(self, yaml_path: Path | str = _DEFAULT_YAML):
        self.yaml_path = Path(yaml_path)
        self.alias_to_canonical: dict[str, str] = {}
        self.canonical_names: list[str] = []
        self._load()

    def _load(self) -> None:
        if not self.yaml_path.exists():
            logger.warning("Locations file not found: %s", self.yaml_path)
            return

        with open(self.yaml_path, encoding="utf-8") as f:
            entries = yaml.safe_load(f) or []

        for entry in entries:
            canonical = entry["canonical"]
            self.canonical_names.append(canonical)
            # Map the canonical name itself (lowercased) to canonical
            self.alias_to_canonical[canonical.lower()] = canonical
            for alias in entry.get("aliases", []):
                self.alias_to_canonical[alias.strip().lower()] = canonical

        logger.info(
            "Loaded %d canonical locations with %d total aliases",
            len(self.canonical_names), len(self.alias_to_canonical),
        )

    def normalize(self, raw_location: Optional[str]) -> Optional[str]:
        """
        Return the canonical location name for a raw string, or None if
        no confident match is found.

        Candidates are tried in ORIGINAL ORDER (left to right). The leftmost
        segment is usually the most specific subarea, so we trust that order
        over arbitrary heuristics like string length.
        """
        if not raw_location:
            return None

        candidates = self._candidate_tokens(raw_location)
        if not candidates:
            return None

        # 1. Exact alias match — first candidate that hits, wins.
        for token in candidates:
            if token in self.alias_to_canonical:
                return self.alias_to_canonical[token]

        # 2. Fuzzy match — same order, first confident match wins.
        for token in candidates:
            match, score, _ = process.extractOne(
                token,
                list(self.alias_to_canonical.keys()),
                scorer=fuzz.WRatio,
            )
            if score >= FUZZY_THRESHOLD:
                return self.alias_to_canonical[match]

        return None

    @staticmethod
    def _candidate_tokens(raw_location: str) -> list[str]:
        """
        Split a raw location into candidate tokens in original order.

        "3rd Avenue, Banana Island, Ikoyi, Lagos"
            -> ["3rd avenue", "banana island", "ikoyi"]

        "Lekki Phase 1, Lekki, Lagos"
            -> ["lekki phase 1", "lekki"]

        We strip the state (usually "lagos" or "abuja") so it doesn't
        match every listing to a generic "Lagos" bucket.
        """
        parts = [p.strip().lower() for p in raw_location.split(",") if p.strip()]

        STATE_TOKENS = {
            "lagos", "abuja", "fct", "nigeria",
            "lagos state", "fct abuja", "lagos, nigeria",
        }
        parts = [p for p in parts if p not in STATE_TOKENS]

        return parts