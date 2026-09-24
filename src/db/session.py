"""Database engine and session factory. Supports SQLite locally and PostgreSQL on Streamlit Cloud."""
from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker

from config.settings import settings


def _get_database_url() -> str:
    """
    Return the database URL.
    
    Priority:
      1. DATABASE_URL environment variable (set in Streamlit Cloud secrets)
      2. settings.database_url (from .env, defaults to SQLite)
    """
    # Streamlit Cloud secrets are exposed as environment variables
    cloud_url = os.getenv("DATABASE_URL")
    if cloud_url and cloud_url.startswith("postgresql"):
        return cloud_url
    
    return settings.database_url


db_url = _get_database_url()

# SQLite needs the parent directory to exist; PostgreSQL doesn't
if db_url.startswith("sqlite"):
    _db_path = db_url.replace("sqlite:///", "")
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

# PostgreSQL on Supabase needs SSL
connect_args = {}
if db_url.startswith("postgresql"):
    connect_args = {"sslmode": "require"}

engine = create_engine(
    db_url,
    echo=False,
    future=True,
    pool_pre_ping=True,  # reconnect if the connection died
    connect_args=connect_args,
)

SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Context manager for transactional access to the DB."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()