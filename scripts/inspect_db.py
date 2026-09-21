"""Quick inspection of the database — counts and median rents.

Usage:
    python -m scripts.inspect_db
"""
from sqlalchemy import func, select

from src.db.session import session_scope
from src.models import Listing, PriceHistory


def main() -> None:
    with session_scope() as session:
        # Totals
        total_listings = session.scalar(select(func.count(Listing.id)))
        total_prices = session.scalar(select(func.count(PriceHistory.id)))

        print(f"Listings  : {total_listings}")
        print(f"Prices    : {total_prices}\n")

        # Summary per bedroom count (annual rent)
        stmt = (
            select(
                Listing.bedrooms,
                func.count(Listing.id).label("n"),
                func.avg(Listing.price_annual_ngn).label("avg_annual"),
                func.min(Listing.price_annual_ngn).label("min_annual"),
                func.max(Listing.price_annual_ngn).label("max_annual"),
            )
            .where(Listing.purpose == "rent", Listing.price_annual_ngn.isnot(None))
            .group_by(Listing.bedrooms)
            .order_by(Listing.bedrooms)
        )
        rows = session.execute(stmt).all()

        print(f"{'Bedrooms':<10}{'Count':<8}{'Avg NGN/yr':<18}{'Min NGN/yr':<18}{'Max NGN/yr':<18}")
        print("-" * 72)
        for bedrooms, n, avg_ann, min_ann, max_ann in rows:
            label = str(bedrooms) if bedrooms is not None else "n/a"
            print(f"{label:<10}{n:<8}{avg_ann:>14,.0f}  {min_ann:>14,.0f}  {max_ann:>14,.0f}")

        # Sanity print of first 3 listings
        print("\nFirst 3 listings:")
        for listing in session.scalars(select(Listing).limit(3)):
            annual = listing.price_annual_ngn or 0
            print(f"  [{listing.source}:{listing.source_id}] {listing.title[:60]}")
            print(f"     {listing.raw_location}")
            print(f"     NGN {annual:,.0f}/yr  ({listing.bedrooms} bed)")


if __name__ == "__main__":
    main()