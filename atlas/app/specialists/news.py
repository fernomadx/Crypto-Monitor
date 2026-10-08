"""News and Events Specialist — public RSS sources."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import feedparser
import httpx

from app.core.enums import Bias, SpecialistName
from app.core.logging import get_logger
from app.schemas import MarketSnapshot, SpecialistAssessment
from app.specialists.base import BaseSpecialist

logger = get_logger(__name__)

PUBLIC_FEEDS = [
    ("https://www.coindesk.com/arc/outboundfeeds/rss/", "coindesk", 0.7),
    ("https://cointelegraph.com/rss", "cointelegraph", 0.65),
]

CATEGORY_KEYWORDS: dict[str, list[str]] = {
    "Fed": ["fed", "fomc", "powell", "federal reserve"],
    "inflação": ["inflation", "cpi", "pce", "inflação"],
    "emprego": ["jobs", "payroll", "unemployment", "nfp"],
    "regulação": ["sec", "regulation", "ban", "etf approval", "regulação"],
    "ETF": ["etf", "spot bitcoin etf", "ibit", "fbtc"],
    "exchange": ["binance", "coinbase", "exchange", "hack"],
    "geopolítica": ["war", "sanctions", "geopolit"],
    "macro": ["gdp", "rates", "treasury", "dxy"],
    "cripto": ["bitcoin", "btc", "crypto", "ethereum"],
}


class NewsEventsSpecialist(BaseSpecialist):
    name = SpecialistName.NEWS_EVENTS
    model_version = "0.1.0"

    def __init__(self, client: httpx.AsyncClient | None = None):
        self._client = client

    async def _fetch_feed(self, url: str) -> str:
        if self._client is not None:
            response = await self._client.get(url, follow_redirects=True)
            response.raise_for_status()
            return response.text
        async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text

    def _categorize(self, title: str) -> str:
        lower = title.lower()
        for category, keys in CATEGORY_KEYWORDS.items():
            if any(k in lower for k in keys):
                return category
        return "cripto"

    def _direction_hint(self, title: str) -> str:
        lower = title.lower()
        bull = ["approval", "inflow", "surge", "rally", "record", "etf approved"]
        bear = ["hack", "ban", "outflow", "crash", "lawsuit", "sec charges", "exploit"]
        if any(w in lower for w in bull):
            return "LONG_BIAS"
        if any(w in lower for w in bear):
            return "SHORT_BIAS"
        return "UNCLEAR"

    async def collect_headlines(self, limit: int = 15) -> list[dict[str, Any]]:
        collected_at = datetime.now(UTC)
        items: list[dict[str, Any]] = []
        seen: set[str] = set()
        for url, source, reliability in PUBLIC_FEEDS:
            try:
                raw = await self._fetch_feed(url)
                parsed = feedparser.parse(raw)
                for entry in parsed.entries[:10]:
                    title = (entry.get("title") or "").strip()
                    if not title:
                        continue
                    key = title.lower()
                    if key in seen:
                        continue
                    seen.add(key)
                    published = entry.get("published_parsed") or entry.get("updated_parsed")
                    if published:
                        pub_ts = datetime(
                            int(published[0]),
                            int(published[1]),
                            int(published[2]),
                            int(published[3]),
                            int(published[4]),
                            int(published[5]),
                            tzinfo=UTC,
                        )
                    else:
                        pub_ts = collected_at
                    items.append(
                        {
                            "title": title,
                            "source": source,
                            "url": entry.get("link", url),
                            "published_at": pub_ts.isoformat(),
                            "collected_at": collected_at.isoformat(),
                            "category": self._categorize(title),
                            "entities": ["BTC"] if "bitcoin" in title.lower() or "btc" in title.lower() else [],
                            "relevance": 0.8 if "bitcoin" in title.lower() or "btc" in title.lower() else 0.4,
                            "direction_hint": self._direction_hint(title),
                            "source_reliability": reliability,
                            "host": urlparse(url).netloc,
                        }
                    )
            except Exception as exc:  # noqa: BLE001
                logger.warning("news_feed_failed", source=source, error=str(exc))
        items.sort(key=lambda x: x["relevance"], reverse=True)
        return items[:limit]

    async def analyze(
        self,
        snapshot: MarketSnapshot,
        context: dict[str, Any] | None = None,
    ) -> SpecialistAssessment:
        context = context or {}
        headlines = context.get("headlines")
        if headlines is None:
            try:
                headlines = await self.collect_headlines()
            except Exception as exc:  # noqa: BLE001
                return self.unavailable(snapshot.symbol, "1h", f"news fetch failed: {exc}")

        if not headlines:
            return self.unavailable(snapshot.symbol, "1h", "no public headlines")

        evidence: list = []
        risks: list[str] = []
        score = 0.0
        for item in headlines[:8]:
            evidence.append(
                self.evidence(
                    f"[{item['category']}] {item['title']} ({item['source']})",
                    weight=float(item.get("relevance", 0.4)) * float(item.get("source_reliability", 0.5)),
                    source=item.get("source", "news"),
                )
            )
            hint = item.get("direction_hint")
            if hint == "LONG_BIAS":
                score += 0.1 * float(item.get("relevance", 0.4))
            elif hint == "SHORT_BIAS":
                score -= 0.1 * float(item.get("relevance", 0.4))
                risks.append(f"Notícia adversa: {item['title'][:80]}")

        evidence.append(
            self.evidence(
                "Notícia não prova causalidade do movimento de preço; medir reação antes/depois em avaliações.",
                weight=0.3,
                source="methodology",
            )
        )

        bias = Bias.LONG if score > 0.15 else Bias.SHORT if score < -0.15 else Bias.NEUTRAL
        conf = self.dampen_confidence(
            min(0.55, 0.25 + abs(score)),
            sample_size=len(headlines),
            min_sample=3,
            data_quality=min(snapshot.data_quality, 0.7),
        )

        return SpecialistAssessment(
            specialist=self.name,
            timestamp=self._now(),
            symbol=snapshot.symbol,
            timeframe="1h",
            bias=bias,
            confidence=conf,
            data_quality=0.6,
            evidence=evidence,
            risks=risks,
            invalidation_conditions=["Headline material contraditória de fonte de alta confiabilidade"],
            alternative_hypotheses=["Ruído de mídia sem impacto persistente no preço"],
            metrics={"headlines": headlines[:10], "score": round(score, 4)},
            model_version=self.model_version,
            errors=[],
            availability="AVAILABLE",
        )
