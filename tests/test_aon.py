from __future__ import annotations

import asyncio
import json

import httpx

from analecta.aon import AonClient, SITE

HIT = {
    "_id": "action-2376",
    "_source": {"id": "action-2376", "name": "Grapple", "type": "Action", "category": "action",
                "url": "/Actions.aspx?ID=2376", "summary": "Attempt an Athletics check.",
                "primary_source_raw": "Player Core pg. 235", "legacy_id": ["action-35"],
                "markdown": "Full **text** of Grapple."},
}
LEGACY = {"_id": "action-35", "_source": {"id": "action-35", "name": "Grapple", "type": "Action",
          "url": "/Actions.aspx?ID=35", "summary": "Old.", "primary_source_raw": "Core Rulebook pg. 242",
          "remaster_id": ["action-2376"]}}


def client(handler, **kw):
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), headers={"User-Agent": "analecta-discord-bot"})
    kw.setdefault("min_interval", 0)
    return AonClient(http=http, **kw)


def ok(hits):
    return lambda req: httpx.Response(200, json={"hits": {"hits": hits}})


def test_search_formats_links_and_flavour():
    c = client(ok([HIT, LEGACY]))
    out = asyncio.run(c.search("grapple"))
    assert f"{SITE}/Actions.aspx?ID=2376" in out and "Remaster" in out
    assert "LEGACY" in out and "Player Core pg. 235" in out


def test_request_shape_and_filters():
    seen = {}

    def handler(req):
        seen["body"] = json.loads(req.content)
        seen["ua"] = req.headers["user-agent"]
        return httpx.Response(200, json={"hits": {"hits": []}})

    c = client(handler)
    out = asyncio.run(c.search("  grapple  ", category="Action", size=99))
    assert "No results" in out
    assert seen["ua"] == "analecta-discord-bot"
    assert seen["body"]["size"] == 8
    assert {"term": {"category": "action"}} in seen["body"]["query"]["bool"]["filter"]


def test_cache_avoids_second_request():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"hits": {"hits": [HIT]}})

    c = client(handler, cache_seconds=60)
    asyncio.run(c.search("grapple")); asyncio.run(c.search("Grapple"))
    assert len(calls) == 1


def test_cache_expires():
    t = [0.0]
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(200, json={"hits": {"hits": [HIT]}})

    c = client(handler, cache_seconds=60, clock=lambda: t[0])
    asyncio.run(c.search("grapple")); t[0] = 120
    asyncio.run(c.search("grapple"))
    assert len(calls) == 2


def test_kill_switch_makes_no_request():
    c = client(lambda r: (_ for _ in ()).throw(AssertionError("should not call")), enabled=False)
    assert "switched off" in asyncio.run(c.search("x"))
    assert "switched off" in asyncio.run(c.get("action-1"))


def test_failures_back_off():
    calls = []

    def handler(req):
        calls.append(1)
        return httpx.Response(500)

    t = [0.0]
    c = client(handler, clock=lambda: t[0])
    for i in range(3):
        assert "did not answer" in asyncio.run(c.search(f"q{i}"))
    assert "unreachable" in asyncio.run(c.search("q9"))
    assert len(calls) == 3
    t[0] = 500
    asyncio.run(c.search("q10"))
    assert len(calls) == 4


def test_get_truncates_and_validates_id():
    big = {"_id": "x", "_source": {**HIT["_source"], "markdown": "z" * 9000}}
    c = client(ok([big]))
    out = asyncio.run(c.get("action-2376"))
    assert "URL: " + SITE in out and "[truncated" in out and len(out) < 6200
    assert "Invalid id" in asyncio.run(c.get("../../etc"))


def test_min_interval_spaces_requests():
    import time

    c = client(ok([HIT]), min_interval=0.2)
    start = time.monotonic()
    asyncio.run(c.search("a")); asyncio.run(c.search("b"))
    assert time.monotonic() - start >= 0.19
