"""
lib/news_sources.py — ingesta de notícias.

Fontes:
    1. RSS: CoinDesk, The Block, Decrypt
    2. CryptoPanic API (free tier)
    3. NewsAPI (free tier)

Retorna lista de dicts: {title, url, source, published}
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Generator

import feedparser
import requests

logger = logging.getLogger(__name__)

CRYPTOPANIC_KEY = os.environ.get("CRYPTOPANIC_API_KEY", "")
NEWS_API_KEY = os.environ.get("NEWS_API_KEY", "")

RSS_FEEDS = {
    "coindesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "theblock": "https://www.theblock.co/rss.xml",
    "decrypt": "https://decrypt.co/feed",
}

CRYPTO_KEYWORDS = ["bitcoin", "btc", "ethereum", "eth", "solana", "sol", "crypto", "defi", "blockchain"]


def _recent_cutoff(minutes: int = 20) -> datetime:
    return datetime.now(timezone.utc) - timedelta(minutes=minutes)


def _parse_rss_date(entry) -> datetime | None:
    if hasattr(entry, "published_parsed") and entry.published_parsed:
        return datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
    return None


def fetch_rss(max_age_minutes: int = 20) -> list[dict]:
    cutoff = _recent_cutoff(max_age_minutes)
    articles = []
    for source, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            for entry in feed.entries:
                pub = _parse_rss_date(entry)
                if pub and pub < cutoff:
                    continue  # artigo velho
                articles.append({
                    "title": entry.get("title", "").strip(),
                    "url": entry.get("link", ""),
                    "source": source,
                    "published": pub.isoformat() if pub else None,
                })
        except Exception as exc:
            logger.warning("RSS fetch failed [%s]: %s", source, exc)
    return articles


def fetch_cryptopanic(max_age_minutes: int = 20) -> list[dict]:
    if not CRYPTOPANIC_KEY:
        logger.debug("CRYPTOPANIC_API_KEY não configurado, pulando")
        return []
    try:
        resp = requests.get(
            "https://cryptopanic.com/api/v1/posts/",
            params={
                "auth_token": CRYPTOPANIC_KEY,
                "public": "true",
                "kind": "news",
                "currencies": "BTC,ETH,SOL",
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        cutoff = _recent_cutoff(max_age_minutes)
        articles = []
        for item in data.get("results", []):
            pub_str = item.get("published_at", "")
            try:
                pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
            except Exception:
                pub = None
            if pub and pub < cutoff:
                continue
            articles.append({
                "title": item.get("title", "").strip(),
                "url": item.get("url", ""),
                "source": "cryptopanic",
                "published": pub.isoformat() if pub else None,
            })
        return articles
    except Exception as exc:
        logger.warning("CryptoPanic fetch failed: %s", exc)
        return []


def fetch_newsapi(max_age_minutes: int = 20) -> list[dict]:
    if not NEWS_API_KEY:
        logger.debug("NEWS_API_KEY não configurado, pulando")
        return []
    try:
        from_dt = _recent_cutoff(max_age_minutes).strftime("%Y-%m-%dT%H:%M:%S")
        resp = requests.get(
            "https://newsapi.org/v2/everything",
            params={
                "apiKey": NEWS_API_KEY,
                "q": "bitcoin OR ethereum OR solana OR crypto",
                "language": "en",
                "sortBy": "publishedAt",
                "from": from_dt,
                "pageSize": 30,
            },
            timeout=10,
        )
        resp.raise_for_status()
        data = resp.json()
        articles = []
        for item in data.get("articles", []):
            articles.append({
                "title": item.get("title", "").strip(),
                "url": item.get("url", ""),
                "source": f"newsapi:{item.get('source', {}).get('name', 'unknown')}",
                "published": item.get("publishedAt"),
            })
        return articles
    except Exception as exc:
        logger.warning("NewsAPI fetch failed: %s", exc)
        return []


def fetch_all(max_age_minutes: int = 20) -> list[dict]:
    """Agrega todas as fontes, deduplica por URL."""
    seen: set[str] = set()
    all_articles = []
    for article in (
        fetch_rss(max_age_minutes)
        + fetch_cryptopanic(max_age_minutes)
        + fetch_newsapi(max_age_minutes)
    ):
        url = article.get("url", "")
        if url and url in seen:
            continue
        if url:
            seen.add(url)
        if article.get("title"):
            all_articles.append(article)
    logger.info("News fetch: %d artigos únicos", len(all_articles))
    return all_articles
