from collections.abc import Generator

import pytest
from sqlalchemy.orm import Session

from app.db.base import SessionLocal


@pytest.fixture
def db() -> Generator[Session, None, None]:
    """A real DB session against the same Postgres CI already runs migrations
    against (DATABASE_URL). Used only by tests that need real SQL semantics
    (e.g. jobs.py's SELECT ... FOR UPDATE SKIP LOCKED / unique-constraint
    conflict detection) that a mock can't stand in for."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.rollback()
        session.close()
