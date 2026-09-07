"""Utility helpers."""

from __future__ import annotations

from datetime import UTC, datetime

from app.utils.jsonable import to_jsonable


def utcnow() -> datetime:
    return datetime.now(UTC)


__all__ = ["utcnow", "to_jsonable"]
