"""Shared test fixtures."""

from __future__ import annotations

from collections.abc import AsyncGenerator
from datetime import UTC, datetime, timedelta

import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import Settings, get_settings
from app.database import get_session
from app.main import create_app
from app.models import Base
from app.schemas import CandleDTO

TEST_DATABASE_URL = "postgresql+asyncpg://atlas:atlas@localhost:5432/atlas_test"


@pytest.fixture(scope="session")
def settings() -> Settings:
    get_settings.cache_clear()
    return Settings(
        env="test",
        database_url=TEST_DATABASE_URL,
        debug=False,
        min_candles=30,
    )


@pytest_asyncio.fixture
async def session(settings: Settings) -> AsyncGenerator[AsyncSession, None]:
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)
    async with factory() as sess:
        yield sess
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest_asyncio.fixture
async def client(session: AsyncSession, settings: Settings) -> AsyncGenerator[AsyncClient, None]:
    get_settings.cache_clear()
    app = create_app()

    async def _override() -> AsyncGenerator[AsyncSession, None]:
        yield session

    app.dependency_overrides[get_session] = _override
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac
    app.dependency_overrides.clear()
    get_settings.cache_clear()


def make_candles(
    n: int = 100,
    start_price: float = 50000.0,
    trend: float = 0.001,
    timeframe: str = "1h",
) -> list[CandleDTO]:
    now = datetime.now(UTC)
    candles: list[CandleDTO] = []
    price = start_price
    for i in range(n):
        open_ = price
        close = price * (1 + trend)
        high = max(open_, close) * 1.002
        low = min(open_, close) * 0.998
        ts = now - timedelta(hours=n - i)
        candles.append(
            CandleDTO(
                symbol="BTC/USDT",
                timeframe=timeframe,
                open_time=ts,
                open=open_,
                high=high,
                low=low,
                close=close,
                volume=1000 + i,
                source="test",
                collected_at=now,
                event_time=ts,
                latency_ms=10.0,
                completeness=1.0,
                raw_payload_hash=f"h{i}",
            )
        )
        price = close
    return candles
