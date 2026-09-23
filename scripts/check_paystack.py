"""Quick diagnostic for Paystack configuration."""
from config.settings import settings


def main() -> None:
    key = settings.paystack_secret_key
    print(f"Length        : {len(key)}")
    print(f"Prefix        : {key[:12]}...")
    print(f"Suffix        : ...{key[-4:]}")
    print(f"Starts sk_test: {key.startswith('sk_test_')}")
    print(f"Starts sk_live: {key.startswith('sk_live_')}")
    print(f"Looks valid   : {key.startswith('sk_test_') and len(key) > 40}")

    # Show any suspicious characters
    if key != key.strip():
        print(f"WARNING: has leading/trailing whitespace!")
    if '"' in key or "'" in key:
        print(f"WARNING: contains quotes!")
    if " " in key.strip():
        print(f"WARNING: contains internal spaces!")
    if "your_" in key.lower():
        print(f"WARNING: still has placeholder text!")


if __name__ == "__main__":
    main()