"""Macro adapter — free public economic indicators.

Default: FRED API (free tier, needs API_KEY).
Fallback: Treasury.gov / IMF data.
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SchemaError(Exception):
    pass


class MacroAdapter:
    """Fetches macro indicators: DXY, 10Y yield, VIX-like crypto sentiment."""

    SCHEMA_VERSION = "v1"

    def __init__(self) -> None:
        self._api_key = os.getenv("MACRO_API_KEY", "")
        self._fred_key = os.getenv("FRED_API_KEY", "")

    async def fetch(self, asset: str) -> dict[str, Any]:
        result = self._empty()

        # Crypto Fear & Greed Index (free, no key)
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get("https://api.alternative.me/fng/?limit=1")
                if resp.status_code == 200:
                    data = resp.json()
                    if data.get("data"):
                        entry = data["data"][0]
                        result["fear_greed_index"] = int(entry.get("value", 50))
                        result["fear_greed_label"] = entry.get("value_classification", "Neutral")
                        result["source"] = "alternative.me"
        except Exception:
            pass

        # DXY from FRED (if key provided)
        if self._fred_key:
            try:
                async with httpx.AsyncClient(timeout=10) as client:
                    resp = await client.get(
                        "https://api.stlouisfed.org/fred/series/observations",
                        params={
                            "series_id": "DTWEXBGS",
                            "api_key": self._fred_key,
                            "file_type": "json",
                            "sort_order": "desc",
                            "limit": 1,
                        },
                    )
                    if resp.status_code == 200:
                        data = resp.json()
                        obs = data.get("observations", [])
                        if obs:
                            result["dxy"] = float(obs[0].get("value", 0))
            except Exception:
                pass

        return result

    def _empty(self) -> dict:
        return {"fear_greed_index": 50, "source": "none", "schema_version": self.SCHEMA_VERSION}
