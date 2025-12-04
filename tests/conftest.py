"""Shared pytest fixtures for database integrity tests."""

from __future__ import annotations

import sys
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import pytest
from pydantic_core import ValidationError
from sqlalchemy import Engine
from sqlalchemy import event
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session
from sqlalchemy.orm import sessionmaker

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SRC_ROOT = PROJECT_ROOT / "src"
if str(SRC_ROOT) not in sys.path:
    sys.path.insert(0, str(SRC_ROOT))

from final_project import LogLevels  # noqa: E402
from final_project.db import Base  # noqa: E402
from final_project.db import connect  # noqa: E402


@pytest.fixture(scope="session")
def sqlite_engine() -> Engine:
    """Connect to the configured SQLite database and ensure schema exists."""
    try:
        engine = connect(LogLevels.ERROR)
    except (
        ValidationError,
        RuntimeError,
        SQLAlchemyError,
    ) as exc:  # pragma: no cover - depends on local env
        pytest.skip(f"Database configuration unavailable: {exc}")
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture
def db_session(sqlite_engine: Engine) -> Iterator[Session]:
    """Provide a transactional SQLAlchemy session for each test."""
    connection = sqlite_engine.connect()
    transaction = connection.begin()
    session_factory = sessionmaker(bind=connection, expire_on_commit=False)
    session = session_factory()
    connection.begin_nested()

    def _restart_savepoint(
        _session: Session,
        transaction: Any,
    ) -> None:  # pragma: no cover
        if transaction.nested and not getattr(transaction._parent, "nested", False):
            connection.begin_nested()

    event.listen(session, "after_transaction_end", _restart_savepoint)

    try:
        yield session
    finally:
        session.close()
        transaction.rollback()
        connection.close()
