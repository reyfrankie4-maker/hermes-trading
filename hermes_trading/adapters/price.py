"""Price adapter — free public endpoints for market data.

Default: Binance public API (no key required).
Premium override via .env: PROVIDER_API_KEY.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SchemaError(Exception):
    pass


class PriceAdapter:
    """Fetches current price + RSI for a given asset.

    Uses Binance public REST API by default.
    Falls back to CoinGecko if Binance fails.
    """

    SCHEMA_VERSION = "v1"

    def __init__(self) -> None:
        self._api_key = os.getenv("PROVIDER_API_KEY", "")

    async def fetch(self, asset: str) -> dict[str, Any]:
        symbol = asset.replace("/", "")

        # Try Binance first
        data = await self._fetch_binance(symbol)
        if data and data.get("price", 0) > 0:
            return data

        # Fallback to CoinGecko
        data = await self._fetch_coingecko(asset)
        if data:
            return data

        return {"price": 0, "rsi": 50, "schema_version": self.SCHEMA_VERSION}

    async def _fetch_binance(self, symbol: str) -> dict | None:
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Latest price
                ticker = await client.get(f"https://api.binance.com/api/v3/ticker/price?symbol={symbol}")
                if ticker.status_code != 200:
                    return None
                price_data = ticker.json()
                price = float(price_data.get("price", 0))

                # 14-period RSI from 1h candles
                klines = await client.get(
                    f"https://api.binance.com/api/v3/klines?symbol={symbol}&interval=1h&limit=15"
                )
                if klines.status_code != 200:
                    return {"price": price, "rsi": 50, "schema_version": self.SCHEMA_VERSION}

                candles = klines.json()
                closes = [float(c[4]) for c in candles]
                rsi = self._compute_rsi(closes)

                return {
                    "price": price,
                    "rsi": round(rsi, 2),
                    "schema_version": self.SCHEMA_VERSION,
                    "source": "binance",
                }
        except Exception:
            return None

    async def _fetch_coingecko(self, asset: str) -> dict | None:
        try:
            # Map BTC/USDC → bitcoin, ETH/USDC → ethereum, etc.
            coin_map = {
                "BTC": "bitcoin", "ETH": "ethereum", "SOL": "solana",
                "BNB": "bnb", "DOGE": "dogecoin", "XRP": "ripple",
                "ADA": "cardano", "AVAX": "avalanche-2", "DOT": "polkadot",
            }
            base = asset.split("/")[0]
            coin_id = coin_map.get(base, base.lower())

            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    f"https://api.coingecko.com/api/v3/coins/{coin_id}",
                    params={"localization": "false", "tickers": "false",
                            "community_data": "false", "developer_data": "false"},
                )
                if resp.status_code != 200:
                    return None
                data = resp.json()
                price = data.get("market_data", {}).get("current_price", {}).get("usd", 0)
                return {
                    "price": float(price) if price else 0,
                    "rsi": 50,
                    "schema_version": self.SCHEMA_VERSION,
                    "source": "coingecko",
                }
        except Exception:
            return None

    @staticmethod
    def _compute_rsi(closes: list[float], period: int = 14) -> float:
        if len(closes) < period + 1:
            return 50.0
        gains, losses = 0.0, 0.0
        for i in range(-period, 0):
            diff = closes[i] - closes[i - 1]
            if diff > 0:
                gains += diff
            else:
                losses -= diff
        avg_gain = gains / period
        avg_loss = losses / period
        if avg_loss == 0:
            return 100.0
        rs = avg_gain / avg_loss
        return 100.0 - (100.0 / (1.0 + rs))
