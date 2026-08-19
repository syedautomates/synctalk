"""Idempotency-Key support for the real-cost/side-effecting POST endpoints.

claude.md's M7 hardening says "idempotency keys on all POSTs"; applied here to the
handful of routes where a duplicate submission has a real cost or duplicates a real
side effect (voice cloning, look generation, video creation) rather than literally
every POST -- see DECISIONS.md's M7 entry for the scoping rationale.

Usage in a route:

    cached = idempotency.get_cached(db, key, ENDPOINT)
    if cached is not None:
        return JSONResponse(status_code=cached.status_code, content=cached.body)
    if key is not None and not idempotency.claim(db, key, ENDPOINT):
        raise HTTPException(409, "A request with this Idempotency-Key is already in progress.")
    ... do the real work, building `response_body: dict` ...
    if key is not None:
        idempotency.store_result(db, key, ENDPOINT, status_code, response_body)
    return response_body
"""

from dataclasses import dataclass
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db.models import IdempotencyKey


@dataclass
class CachedResponse:
    status_code: int
    body: dict[str, Any]


def get_cached(db: Session, key: str | None, endpoint: str) -> CachedResponse | None:
    if key is None:
        return None
    row = db.get(IdempotencyKey, (key, endpoint))
    if row is None or row.status_code is None or row.response_body is None:
        return None
    return CachedResponse(status_code=row.status_code, body=row.response_body)


def claim(db: Session, key: str, endpoint: str) -> bool:
    """Attempts to claim this key for a fresh request. Returns False if another
    request already claimed it (either still in flight, or already completed but
    somehow not caught by get_cached -- treat both as "don't proceed")."""
    try:
        db.add(IdempotencyKey(key=key, endpoint=endpoint))
        db.commit()
        return True
    except IntegrityError:
        db.rollback()
        return False


def store_result(
    db: Session, key: str, endpoint: str, status_code: int, body: dict[str, Any]
) -> None:
    row = db.get(IdempotencyKey, (key, endpoint))
    if row is None:
        # claim() was never called (e.g. an internal error before it) -- store anyway
        # so a retry with the same key still gets a consistent cached response.
        row = IdempotencyKey(key=key, endpoint=endpoint)
        db.add(row)
    row.status_code = status_code
    row.response_body = body
    db.commit()


def release(db: Session, key: str, endpoint: str) -> None:
    """Deletes an in-flight claim so a retry isn't permanently blocked. Callers must
    invoke this from an exception handler around the claimed work -- otherwise a request
    that fails after claim() but before store_result() would leave the key stuck
    forever (get_cached only recognizes a *resolved* row, so a retry would just hit
    claim() again and get a false "already in progress")."""
    row = db.get(IdempotencyKey, (key, endpoint))
    if row is not None and row.status_code is None:
        db.delete(row)
        db.commit()
