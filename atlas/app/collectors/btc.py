"""BTC market collector — fetch, validate, persist."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.collectors.providers.binance import BinancePublicProvider
from app.collectors.providers.fallback import FallbackMarketProvider
from app.config import Settings, get_settings
from app.core.logging import get_logger
from app.models import Candle, CollectionMeta, MarketSnapshotRecord
from app.schemas import CandleDTO, MarketSnapshot

logger = get_logger(__name__)


class BtcMarketCollector:
    def __init__(
        self,
        session: AsyncSession,
        provider: BinancePublicProvider | FallbackMarketProvider | None = None,
        settings: Settings | None = None,
    ):
        self.session = session
        self.settings = settings or get_settings()
        self.provider = provider or FallbackMarketProvider(self.settings)

    async def collect(
        self,
        timeframes: list[str] | None = None,
        limit: int = 200,
    ) -> MarketSnapshot:
        tfs = timeframes or self.settings.timeframes
        symbol = self.settings.btc_symbol
        by_tf: dict[str, list[CandleDTO]] = {}
        sources: set[str] = set()
        quality_scores: list[float] = []

        for tf in tfs:
            candles = await self.provider.fetch_ohlcv(symbol, tf, limit=limit)
            self._validate_candles(candles, tf)
            await self._persist_candles(candles)
            by_tf[tf] = candles
            sources.add(self.provider.name)
            quality_scores.append(self._timeframe_quality(candles))

        price = float(by_tf.get("1h", by_tf.get("15m", next(iter(by_tf.values()))))[-1].close)
        latest_event = max(c[-1].event_time for c in by_tf.values())
        lag_sec = (datetime.now(UTC) - latest_event).total_seconds()
        data_quality = sum(quality_scores) / max(len(quality_scores), 1)
        if lag_sec > self.settings.max_data_lag_sec:
            data_quality *= 0.7

        snapshot = MarketSnapshot(
            symbol=symbol,
            price=price,
            timestamp=datetime.now(UTC),
            timeframes=by_tf,
            data_quality=round(max(0.0, min(1.0, data_quality)), 4),
            sources=sorted(sources),
            lag_sec=lag_sec,
        )
        await self._persist_snapshot(snapshot)
        await self._touch_collection_meta(lag_ms=(lag_sec * 1000), ok=True)
        await self.session.commit()
        logger.info(
            "btc_collect_ok",
            symbol=symbol,
            price=price,
            timeframes=list(by_tf.keys()),
            data_quality=snapshot.data_quality,
        )
        return snapshot

    def _validate_candles(self, candles: list[CandleDTO], timeframe: str) -> None:
        if len(candles) < self.settings.min_candles:
            logger.warning("insufficient_candles", timeframe=timeframe, count=len(candles))
        for candle in candles:
            if candle.high < candle.low:
                raise ValueError(f"invalid OHLC high<low at {candle.open_time}")
            if candle.close <= 0 or candle.open <= 0:
                raise ValueError(f"invalid price at {candle.open_time}")

    def _timeframe_quality(self, candles: list[CandleDTO]) -> float:
        if not candles:
            return 0.0
        score = min(1.0, len(candles) / float(self.settings.min_candles))
        completeness = sum(c.completeness for c in candles) / len(candles)
        return 0.6 * score + 0.4 * completeness

    async def _persist_candles(self, candles: list[CandleDTO]) -> None:
        for candle in candles:
            stmt = (
                insert(Candle)
                .values(
                    symbol=candle.symbol,
                    timeframe=candle.timeframe,
                    open_time=candle.open_time,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=candle.volume,
                    source=candle.source,
                    collected_at=candle.collected_at,
                    event_time=candle.event_time,
                    latency_ms=candle.latency_ms,
                    completeness=candle.completeness,
                    raw_payload_hash=candle.raw_payload_hash,
                )
                .on_conflict_do_nothing(
                    constraint="uq_candle_identity",
                )
            )
            await self.session.execute(stmt)

    async def _persist_snapshot(self, snapshot: MarketSnapshot) -> None:
        record = MarketSnapshotRecord(
            symbol=snapshot.symbol,
            price=snapshot.price,
            timestamp=snapshot.timestamp,
            data_quality=snapshot.data_quality,
            payload=snapshot.model_dump(mode="json"),
        )
        self.session.add(record)

    async def _touch_collection_meta(self, lag_ms: float, ok: bool, error: str | None = None) -> None:
        source_key = getattr(self.provider, "last_provider", None) or self.provider.name
        result = await self.session.execute(
            select(CollectionMeta).where(CollectionMeta.source == source_key)
        )
        meta = result.scalar_one_or_none()
        if meta is None:
            meta = CollectionMeta(source=source_key)
            self.session.add(meta)
        if ok:
            meta.last_success_at = datetime.now(UTC)
            meta.status = "ok"
            meta.last_error = None
        else:
            meta.status = "error"
            meta.last_error = error
        meta.last_latency_ms = lag_ms

    async def latest_snapshot(self) -> MarketSnapshot | None:
        result = await self.session.execute(
            select(MarketSnapshotRecord).order_by(MarketSnapshotRecord.created_at.desc()).limit(1)
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return MarketSnapshot.model_validate(row.payload)

    async def collection_status(self) -> dict[str, Any]:
        result = await self.session.execute(
            select(CollectionMeta).order_by(CollectionMeta.last_success_at.desc().nullslast()).limit(1)
        )
        meta = result.scalar_one_or_none()
        if meta is None:
            return {"source": self.provider.name, "status": "unknown"}
        return {
            "source": meta.source,
            "status": meta.status,
            "last_success_at": meta.last_success_at.isoformat() if meta.last_success_at else None,
            "last_error": meta.last_error,
            "last_latency_ms": meta.last_latency_ms,
        }
