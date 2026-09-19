"""Quick tests for the price parser. Run with: python tests/test_price_parser.py"""
from src.processing.price_parser import parse_price, to_monthly, to_annual


CASES = [
    # (input, expected_price, expected_period)
    ("₦2.5m p.a", 2_500_000, "annual"),
    ("2.5 million yearly", 2_500_000, "annual"),
    ("₦250,000/month", 250_000, "monthly"),
    ("N150M", 150_000_000, None),
    ("₦1.2bn", 1_200_000_000, None),
    ("1.5m per annum", 1_500_000, "annual"),
    ("₦800k yearly", 800_000, "annual"),
    ("450,000 monthly", 450_000, "monthly"),
    ("₦300,000", 300_000, None),
    ("", None, None),
]


def main() -> None:
    passed = 0
    failed = 0

    for raw, expected_price, expected_period in CASES:
        price, period = parse_price(raw)
        ok = (price == expected_price) and (period == expected_period)
        symbol = "[PASS]" if ok else "[FAIL]"
        print(f"{symbol}  {raw!r:30} -> price={price}, period={period}")
        if not ok:
            print(f"        expected: price={expected_price}, period={expected_period}")
            failed += 1
        else:
            passed += 1

    print(f"\n{passed} passed, {failed} failed")

    print("\n--- conversions ---")
    print("Monthly from N2.5m p.a :", to_monthly(2_500_000, "annual"))
    print("Annual from N250k/mo   :", to_annual(250_000, "monthly"))


if __name__ == "__main__":
    main()