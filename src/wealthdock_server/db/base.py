"""Shared SQLAlchemy declarative base for all ORM models."""

from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Base class every ORM model inherits from.

    Alembic's `env.py` imports `Base.metadata` for autogenerating
    migrations, so every model module must be imported somewhere before
    autogeneration runs.
    """
