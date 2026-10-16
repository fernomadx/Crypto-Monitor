"""Shared exceptions."""

from __future__ import annotations


class AtlasError(Exception):
    """Base ATLAS error."""


class DataUnavailableError(AtlasError):
    """Raised when a required data source cannot provide data."""

    def __init__(self, source: str, detail: str = "") -> None:
        self.source = source
        self.detail = detail
        super().__init__(f"DATA_UNAVAILABLE:{source}:{detail}")


class ConfigurationError(AtlasError):
    """Invalid configuration."""


class PersistenceError(AtlasError):
    """Database persistence failure."""
