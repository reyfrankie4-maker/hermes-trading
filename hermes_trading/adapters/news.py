"""News adapter — free public news headlines.

Default: NewsAPI free tier (requires NEWSAPI_KEY in .env but has a free plan).
Fallback: RSS feeds (no key needed).
"""

from __future__ import annotations

import os
from typing import Any

import httpx


class SchemaError(Exception):
    pass


class NewsAdapter:
    """Fetches crypto-related news headlines and sentiment."""

    SCHEMA_VERSION = "v1"

    def __init__(self) -> None:
        self._api_key = os.getenv("NEWSAPI_KEY", "")

    async def fetch(self, asset: str) -> dict[str, Any]:
        base = asset.split("/")[0]

        if self._api_key:
            return await self._fetch_newsapi(base)
        return await self._fetch_rss(base)

    async def _fetch_newsapi(self, coin: str) -> dict:
        result = self._empty()
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                resp = await client.get(
                    "https://newsapi.org/v2/everything",
                    params={
                        "q": coin,
                        "language": "en",
                        "sortBy": "publishedAt",
                        "pageSize": 5,
                        "apiKey": self._api_key,
                    },
                )
                if resp.status_code == 200:
                    data = resp.json()
                    articles = data.get("articles", [])
                    result["headlines"] = [a.get("title", "") for a in articles[:5]]
                    result["total_results"] = data.get("totalResults", 0)
                    result["source"] = "newsapi"
        except Exception:
            pass
        return result

    async def _fetch_rss(self, coin: str) -> dict:
        result = self._empty()
        feeds = [
            f"https://cryptonews-api.com/rss/{coin.lower()}.xml",
            "https://cointelegraph.com/rss",
        ]
        try:
            async with httpx.AsyncClient(timeout=10) as client:
                for feed in feeds:
                    try:
                        resp = await client.get(feed)
                        if resp.status_code == 200:
                            result["raw_rss_length"] = len(resp.text)
                            result["source"] = "rss"
                            break
                    except Exception:
                        continue
        except Exception:
            pass
        return result

    def _empty(self) -> dict:
        return {"headlines": [], "source": "none", "schema_version": self.SCHEMA_VERSION}
