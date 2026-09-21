"""SQLAlchemy declarative base — every model inherits from Base."""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Modern SQLAlchemy 2.0 declarative base class."""
    pass