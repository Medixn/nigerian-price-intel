"""Initialize the PostgreSQL schema on Streamlit Cloud (or any remote DB).

Reads DATABASE_URL from .streamlit/secrets.toml or environment.

Usage:
    python -m scripts.init_cloud_db
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Load from secrets.toml if present (local dev convenience)
try:
    import tomllib
except ImportError:
    tomllib = None

secrets_path = Path(".streamlit/secrets.toml")
if secrets_path.exists() and tomllib:
    with open(secrets_path, "rb") as f:
        secrets = tomllib.load(f)
    for key, value in secrets.items():
        if isinstance(value, str):
            os.environ.setdefault(key, value)

from sqlalchemy import create_engine

from src.models import Base


def main() -> None:
    db_url = os.getenv("DATABASE_URL")
    if not db_url:
        print("[ERROR] DATABASE_URL not set.")
        print("Set it in .streamlit/secrets.toml or as an environment variable.")
        sys.exit(1)

    print(f"Connecting to: {db_url[:40]}...")
    engine = create_engine(db_url, connect_args={"sslmode": "require"} if "postgresql" in db_url else {})
    Base.metadata.create_all(engine)
    print("Schema created.")
    print("Tables:", ", ".join(Base.metadata.tables.keys()))


if __name__ == "__main__":
    main()