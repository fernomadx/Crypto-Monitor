"""Typed configuration for ATLAS."""

from __future__ import annotations

from functools import lru_cache
from typing import Literal

from pydantic import field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="ATLAS_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    env: Literal["development", "test", "production"] = "development"
    app_name: str = "ATLAS"
    version: str = "0.1.0"
    debug: bool = False
    host: str = "0.0.0.0"
    port: int = 8080

    database_url: str = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas"

    btc_symbol: str = "BTC/USDT"
    default_timeframes: str = "5m,15m,1h,4h,1d,1w"
    binance_base_url: str = "https://api.binance.com"
    http_timeout_sec: float = 30.0
    http_retries: int = 3

    fred_api_key: str = ""
    stooq_enabled: bool = True

    max_data_lag_sec: int = 900
    min_candles: int = 50

    @field_validator("database_url")
    @classmethod
    def validate_database_url(cls, value: str) -> str:
        if not value:
            raise ValueError("ATLAS_DATABASE_URL is required")
        if value.startswith("postgresql://"):
            return value.replace("postgresql://", "postgresql+asyncpg://", 1)
        return value

    @property
    def timeframes(self) -> list[str]:
        return [tf.strip() for tf in self.default_timeframes.split(",") if tf.strip()]

    @property
    def is_test(self) -> bool:
        return self.env == "test"


@lru_cache
def get_settings() -> Settings:
    return Settings()
