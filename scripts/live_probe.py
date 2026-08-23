#!/usr/bin/env python
"""Live probe: parses a Netscape cookie file → hits 6 Lenta data endpoints
through our LentaClient. No uvicorn, no Playwright.

Usage:
    uv run python scripts/live_probe.py /tmp/lenta-cookies.txt
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import unquote

from app.client import LentaClient
from app.schemas import AuthState


def parse_netscape(path: Path) -> dict[str, str]:
    cookies: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 7:
            continue
        name, value = parts[5], parts[6]
        cookies[name] = value
    return cookies


def store_id_from_mission(cookies: dict[str, str]) -> str | None:
    raw = cookies.get("App_Cache_MissionAddressMode")
    if not raw:
        return None
    try:
        data = json.loads(unquote(raw))
        ma = data.get("ma", {})
        # ponytail: the Lenta URL API uses the alias `a` (e.g. "3554"),
        # not the internal `i` (4075). Seen in sniffing: /api/v1/stores/3554/skus/...
        return str(ma.get("a") or ma.get("i") or "")
    except Exception:
        return None


async def main() -> int:
    if len(sys.argv) < 2:
        print("usage: live_probe.py <cookies.txt>", file=sys.stderr)
        return 1
    cookies = parse_netscape(Path(sys.argv[1]))
    print(f"=== parsed {len(cookies)} cookies ===")
    for k in ("qrator_jsid", "App_Cache_MPK", "Utk_SessionToken",
              "PassportAccessToken", "App_Cache_CitySlug"):
        v = cookies.get(k, "")
        print(f"  {k}: {'YES' if v else 'NO'} ({len(v)} chars)")

    store_id = store_id_from_mission(cookies)
    print(f"  store_id from App_Cache_MissionAddressMode: {store_id!r}")

    client = LentaClient()
    # Disable Qrator solver entirely, go straight to manual login.
    client._cookies.update(cookies)
    client._phone = "79066399816"
    client._state = AuthState.logged_in
    if store_id:
        client._store_id = store_id

    failures: list[str] = []
    print("\n=== 1. GET /api/v1/me (probe auth) ===")
    try:
        resp = await client._http.get("/api/v1/me", headers=client._request_headers())
        print(f"  status={resp.status_code} ct={resp.headers.get('content-type', '')}")
        text = resp.text
        print(f"  head: {text[:300]}")
        if resp.status_code != 200:
            failures.append("me")
    except Exception as e:
        print(f"  ERROR: {e}")
        failures.append("me")

    print("\n=== 2. get_category_tree() ===")
    try:
        cats = await client.get_category_tree()
        print(f"  OK: {len(cats)} top categories")
        for c in cats[:3]:
            print(f"    - {c.name} (node={c.node_code}, children={len(c.children)})")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        failures.append("categories")

    print("\n=== 3. search('молоко') ===")
    try:
        res = await client.search("молоко", offset=0, limit=5)
        print(f"  OK: total={res.total}, items={len(res.items)}")
        for p in res.items[:3]:
            print(f"    - {p.code} {p.title!r} reg={p.regular_price} disc={p.discount_price}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        failures.append("search")

    print("\n=== 4. get_promo_weekly() ===")
    try:
        promos = await client.get_promo_weekly(limit=20)
        print(f"  OK: {len(promos)} promos")
        for pr in promos[:3]:
            print(f"    - id={pr.id} title={pr.title!r} disc={pr.discount_string!r}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        failures.append("promo_weekly")

    print("\n=== 5. get_promo_crazy() ===")
    try:
        promos = await client.get_promo_crazy()
        print(f"  OK: {len(promos)} crazy promos")
        for pr in promos[:3]:
            print(f"    - id={pr.id} title={pr.title!r} crazy={pr.is_crazy_mass_promo}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        failures.append("promo_crazy")

    print("\n=== 6. get_category_skus(first node) ===")
    try:
        cats = await client.get_category_tree()
        if cats:
            node = cats[0].node_code
            res = await client.get_category_skus(node, offset=0, limit=5)
            print(f"  OK: total={res.total}, items={len(res.items)} for node {node!r}")
            for p in res.items[:3]:
                print(f"    - {p.code} {p.title!r} reg={p.regular_price}")
    except Exception as e:
        print(f"  ERROR: {type(e).__name__}: {e}")
        failures.append("category_skus")

    await client.aclose()
    print(f"\n=== SUMMARY: {6 - len(failures)}/6 ok, failures={failures} ===")
    return 0 if not failures else 2


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))