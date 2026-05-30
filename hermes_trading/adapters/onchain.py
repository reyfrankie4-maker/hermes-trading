"""On-chain adapter — free public blockchain data.

Default: Blockchair / Mempool.space (no key required).
Premium override via .env: ONCHAIN_API_KEY.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SchemaError(Exception):
    pass


class OnchainAdapter:
    """Fetches basic on-chain metrics (mempool size, hashrate trend)."""

    SCHEMA_VERSION = "v1"

    def __init__(self) -> None:
        self._api_key = os.getenv("ONCHAIN_API_KEY", "")

    async def fetch(self, asset: str) -> dict[str, Any]:
        base = asset.split("/")[0]

        if base == "BTC":
            return await self._fetch_btc()
        elif base == "ETH":
            return await self._fetch_eth()
        return self._empty("unsupported_asset")

    async def _fetch_btc(self) -> dict:
        result = self._empty()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Mempool size from mempool.space
                resp = await client.get("https://mempool.space/api/mempool")
                if resp.status_code == 200:
                    data = resp.json()
                    result["mempool_tx_count"] = data.get("count", 0)
                    result["mempool_vsize"] = data.get("vsize", 0)
                    result["source"] = "mempool.space"
        except Exception:
            pass
        return result

    async def _fetch_eth(self) -> dict:
        result = self._empty()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                # Gas price from Etherscan (free tier)
                resp = await client.get(
                    "https://api.etherscan.io/api?module=gastracker&action=gasoracle&apikey="
                )
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("status") == "1":
                        result["gas_price_gwei"] = float(data["result"].get("SafeGasPrice", 0))
                        result["source"] = "etherscan"
        except Exception:
            pass
        return result

    def _empty(self, reason: str = "no_data") -> dict:
        return {
            "schema_version": self.SCHEMA_VERSION,
            "note": reason,
        }
