"""Parse messy Nigerian property price strings into clean numeric values."""
import re
from typing import Optional, Tuple


# Multiplier suffixes, in order of length (longest first) so "million"
# matches before "m". All lowercase.
_MULTIPLIERS = {
    "k": 1_000,
    "m": 1_000_000,
    "million": 1_000_000,
    "billion": 1_000_000_000,
    "bn": 1_000_000_000,
    "b": 1_000_000_000,
}

# Period patterns. Order matters: longer / more specific first.
# Each entry is (regex_pattern, canonical_period).
_PERIOD_PATTERNS = [
    (r"per\s*annum", "annual"),
    (r"per\s*month", "monthly"),
    (r"\bp\.?\s*a\.?\b", "annual"),      # "p.a", "pa", "p a"
    (r"\bp\.?\s*m\.?\b", "monthly"),     # "p.m", "pm", "p m"
    (r"annum", "annual"),
    (r"yearly|\byear\b", "annual"),
    (r"monthly|\bmonth\b", "monthly"),
]


def _clean_text(raw: str) -> str:
    """
    Prepare a raw price string for parsing.

    - lowercase
    - remove Nigerian currency symbol ₦ and standalone N/n prefix
    - remove commas
    - collapse whitespace

    Deliberately does NOT strip all 'n' or 'm' characters — those can be
    meaningful ("bn" = billion, "month" = period).
    """
    text = raw.strip().lower()

    # Remove ₦ symbol
    text = text.replace("₦", "")

    # Remove leading currency "n" (e.g. "n150m") — only at start
    text = re.sub(r"^\s*n\b", "", text)          # "n" as whole word at start
    text = re.sub(r"^n(?=\d)", "", text)         # "n" immediately before a digit

    # Remove commas
    text = text.replace(",", "")

    # Collapse whitespace
    text = re.sub(r"\s+", " ", text).strip()

    return text


def _detect_period(text: str) -> Optional[str]:
    """Return 'annual', 'monthly', or None."""
    for pattern, period in _PERIOD_PATTERNS:
        if re.search(pattern, text):
            return period
    return None


def _extract_price(text: str) -> Optional[float]:
    """
    Extract the numeric price from a cleaned string.

    Handles:
        "2.5m"           -> 2_500_000
        "2.5 million"    -> 2_500_000
        "1.2bn"          -> 1_200_000_000
        "250000"         -> 250_000
        "150000000"      -> 150_000_000
    """
    # Match a number followed by an optional multiplier word/letter.
    # The multiplier must be followed by a word boundary so "250000monthly"
    # is read as 250000, not 250000m + "onthly".
    pattern = r"(\d+(?:\.\d+)?)\s*(k|m|million|billion|bn|b)?(?![a-z])"
    match = re.search(pattern, text)
    if not match:
        return None

    number = float(match.group(1))
    suffix = (match.group(2) or "").lower()
    multiplier = _MULTIPLIERS.get(suffix, 1)

    return round(number * multiplier, 2)


def parse_price(raw: str) -> Tuple[Optional[float], Optional[str]]:
    """
    Parse a Nigerian property price string into (price_ngn, period).

    Examples:
        "₦2.5m p.a"          -> (2500000.0, "annual")
        "2.5 million yearly" -> (2500000.0, "annual")
        "₦250,000/month"     -> (250000.0, "monthly")
        "N150M"              -> (150000000.0, None)
        "₦1.2bn"             -> (1200000000.0, None)
        ""                   -> (None, None)
    """
    if not raw or not raw.strip():
        return None, None

    text = _clean_text(raw)

    period = _detect_period(text)
    price = _extract_price(text)

    if price is None:
        return None, period

    # Sanity check: Nigerian listings are rarely below ₦10,000
    if price < 10_000:
        return None, period

    return price, period


def to_monthly(price: Optional[float], period: Optional[str]) -> Optional[float]:
    """Convert an annual price to its monthly equivalent."""
    if price is None:
        return None
    if period == "annual":
        return round(price / 12, 2)
    if period == "monthly":
        return price
    return None


def to_annual(price: Optional[float], period: Optional[str]) -> Optional[float]:
    """Convert a monthly price to its annual equivalent."""
    if price is None:
        return None
    if period == "monthly":
        return round(price * 12, 2)
    if period == "annual":
        return price
    return None