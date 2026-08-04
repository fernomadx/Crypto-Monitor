"""Provider package."""

from app.collectors.providers.base import MacroDataProvider, MarketDataProvider
from app.collectors.providers.binance import BinancePublicProvider
from app.collectors.providers.bybit import BybitPublicProvider
from app.collectors.providers.coinbase import CoinbasePublicProvider
from app.collectors.providers.fallback import FallbackMarketProvider
from app.collectors.providers.fred import FredProvider
from app.collectors.providers.okx import OkxPublicProvider
from app.collectors.providers.stooq import StooqProvider
from app.collectors.providers.yahoo import YahooMacroProvider

__all__ = [
    "MarketDataProvider",
    "MacroDataProvider",
    "BinancePublicProvider",
    "BybitPublicProvider",
    "CoinbasePublicProvider",
    "OkxPublicProvider",
    "FallbackMarketProvider",
    "StooqProvider",
    "FredProvider",
    "YahooMacroProvider",
]
