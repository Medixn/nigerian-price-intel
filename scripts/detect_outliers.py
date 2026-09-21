"""
Run outlier detection across all listings. Flags (does not delete)
suspicious prices based on peer-group quartiles.

Usage:
    python -m scripts.detect_outliers
"""
from sqlalchemy import select

from src.db.session import session_scope
from src.models import Listing
from src.processing.outlier_detector import detect_outliers


def main() -> None:
    with session_scope() as session:
        summary = detect_outliers(session)
        print("Outlier detection summary:")
        for k, v in summary.items():
            print(f"  {k:<18} : {v}")

        print("\nTop 10 flagged-as-expensive listings:")
        rows = session.scalars(
            select(Listing)
            .where(Listing.is_outlier == True, Listing.outlier_reason.like("suspiciously expensive%"))
            .order_by(Listing.price_annual_ngn.desc())
            .limit(10)
        ).all()
        for listing in rows:
            print(f"  ₦{listing.price_annual_ngn:>14,.0f}  {listing.bedrooms or '?':>3}-bed  {listing.raw_location}")
            print(f"      {listing.title[:70]}")
            print(f"      {listing.outlier_reason}")

        print("\nTop 10 flagged-as-cheap listings:")
        rows = session.scalars(
            select(Listing)
            .where(Listing.is_outlier == True, Listing.outlier_reason.like("suspiciously cheap%"))
            .order_by(Listing.price_annual_ngn.asc())
            .limit(10)
        ).all()
        for listing in rows:
            print(f"  ₦{listing.price_annual_ngn:>14,.0f}  {listing.bedrooms or '?':>3}-bed  {listing.raw_location}")
            print(f"      {listing.title[:70]}")
            print(f"      {listing.outlier_reason}")


if __name__ == "__main__":
    main()