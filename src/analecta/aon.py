"""Live Archives of Nethys lookups through the site's own search backend.

Polite by design: a short in-memory cache, a minimum gap between requests, a clear generic
User-Agent, a back-off after repeated failures, and a switch to turn the whole thing off.
Nothing is stored beyond the short cache, so there is no bulk copy of the site.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import httpx

SEARCH_URL = "https://elasticsearch.aonprd.com/aon/_search"
SITE = "https://2e.aonprd.com"
SEARCH_FIELDS = ["name^6", "name.keyword^10", "trait_raw^2", "summary^2", "text"]
LIST_FIELDS = [
    "id", "name", "category", "type", "url", "summary", "primary_source_raw",
    "rarity", "remaster_id", "legacy_id",
]
MAX_GET_CHARS = 5500
FAILURE_BACKOFF_AFTER = 3
FAILURE_BACKOFF_SECONDS = 120.0
_ID = re.compile(r"^[a-z0-9\-]{3,60}$")


class AonClient:
    def __init__(
        self,
        *,
        enabled: bool = True,
        cache_seconds: int = 900,
        min_interval: float = 2.0,
        user_agent: str = "analecta-discord-bot",
        http: httpx.AsyncClient | None = None,
        clock=time.monotonic,
    ):
        self.enabled = enabled
        self.cache_seconds = cache_seconds
        self.min_interval = min_interval
        self._http = http or httpx.AsyncClient(
            timeout=httpx.Timeout(15.0), headers={"User-Agent": user_agent}, follow_redirects=False
        )
        self._clock = clock
        self._cache: dict[str, tuple[float, str]] = {}
        self._lock = asyncio.Lock()
        self._last_request = -1e9
        self._failures = 0
        self._paused_until = 0.0
        self.requests_made = 0

    async def aclose(self) -> None:
        await self._http.aclose()

    # -- public tools --------------------------------------------------------------
    async def search(self, query: str, category: str = "", size: int = 5) -> str:
        query = " ".join(query.split())[:200]
        if not query:
            return "Empty query."
        size = max(1, min(int(size), 8))
        cat = category.strip().lower()
        key = f"s|{query.lower()}|{cat}|{size}"
        body: dict[str, Any] = {
            "size": size,
            "_source": {"includes": LIST_FIELDS},
            "query": {
                "bool": {
                    "must": [{"multi_match": {"query": query, "fields": SEARCH_FIELDS}}],
                    "should": [{"match_phrase": {"name": {"query": query, "boost": 5}}}],
                    "filter": [{"term": {"exclude_from_search": False}}]
                    + ([{"term": {"category": cat}}] if cat else []),
                }
            },
        }
        return await self._call(key, body, _format_hits)

    async def get(self, doc_id: str) -> str:
        doc_id = doc_id.strip().lower()
        if not _ID.match(doc_id):
            return "Invalid id. Use an id returned by aon_search, such as action-2376."
        body = {
            "size": 1,
            "_source": {"excludes": ["text", "search_markdown"]},
            "query": {"ids": {"values": [doc_id]}},
        }
        return await self._call(f"g|{doc_id}", body, _format_doc)

    # -- plumbing ------------------------------------------------------------------
    async def _call(self, key: str, body: dict[str, Any], fmt) -> str:
        if not self.enabled:
            return "Rules lookup on Archives of Nethys is switched off right now."
        now = self._clock()
        hit = self._cache.get(key)
        if hit and now - hit[0] < self.cache_seconds:
            return hit[1]
        if now < self._paused_until:
            return "Archives of Nethys looks unreachable at the moment; try again in a few minutes."
        async with self._lock:
            wait = self.min_interval - (self._clock() - self._last_request)
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_request = self._clock()
            self.requests_made += 1
            try:
                resp = await self._http.post(SEARCH_URL, json=body)
                resp.raise_for_status()
                data = resp.json()
                text = fmt(data)
            except (httpx.HTTPError, ValueError, KeyError):
                self._failures += 1
                if self._failures >= FAILURE_BACKOFF_AFTER:
                    self._paused_until = self._clock() + FAILURE_BACKOFF_SECONDS
                    self._failures = 0
                return "Archives of Nethys did not answer properly. Say so and do not guess the rule."
            self._failures = 0
        self._store(key, text)
        return text

    def _store(self, key: str, text: str) -> None:
        if len(self._cache) > 300:
            oldest = sorted(self._cache.items(), key=lambda kv: kv[1][0])[:100]
            for k, _ in oldest:
                self._cache.pop(k, None)
        self._cache[key] = (self._clock(), text)


def _flavour(src: dict[str, Any]) -> str:
    if src.get("remaster_id"):
        return "LEGACY (pre-Remaster; a newer version exists)"
    if src.get("legacy_id"):
        return "Remaster"
    return ""


def _format_hits(data: dict[str, Any]) -> str:
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return "No results on Archives of Nethys for that query. Try other words."
    rows = []
    for h in hits:
        s = h.get("_source", {})
        summary = " ".join(str(s.get("summary", "")).split())[:240]
        row = (
            f"id: {s.get('id', h.get('_id'))} | {s.get('name')} | {s.get('type') or s.get('category')}"
            f" | {s.get('primary_source_raw', '')} | {_flavour(s)} | {SITE}{s.get('url', '')}\n  {summary}"
        )
        rows.append(row)
    return "\n".join(rows)


def _format_doc(data: dict[str, Any]) -> str:
    hits = data.get("hits", {}).get("hits", [])
    if not hits:
        return "No such id on Archives of Nethys."
    s = hits[0].get("_source", {})
    body = str(s.get("markdown") or s.get("summary") or "").strip()
    if len(body) > MAX_GET_CHARS:
        body = body[:MAX_GET_CHARS] + "\n[truncated; the link has the rest]"
    head = f"{s.get('name')} | {s.get('type') or s.get('category')} | {s.get('primary_source_raw', '')} | {_flavour(s)}"
    return f"{head}\nURL: {SITE}{s.get('url', '')}\n\n{body}"
