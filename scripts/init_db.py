"""Create all database tables. Run once before first use.

Usage:
    python -m scripts.init_db
"""
from src.db.session import engine
from src.models import Base


def main() -> None:
    Base.metadata.create_all(engine)
    print("Database initialized.")
    print("Tables created:", ", ".join(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()