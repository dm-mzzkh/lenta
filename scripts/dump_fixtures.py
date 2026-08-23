#!/usr/bin/env python
"""Dumps fresh tests/fixtures/*.json from the real lenta.com.

Interactive script: asks for a phone number, sends an SMS, asks for the code.

Usage:
    uv run python scripts/dump_fixtures.py

Requires .env (LENTA_CITY_KEY etc.) and playwright+chromium installed.
"""
from __future__ import annotations

import asyncio
import json
from pathlib import Path
from typing import Any

from app.client import LentaClient

FIXTURES = Path(__file__).resolve().parent.parent / "tests" / "fixtures"


async def main() -> None:
    FIXTURES.mkdir(parents=True, exist_ok=True)
    phone = input("phone (7XXXXXXXXXX): ").strip()
    client = LentaClient()
    await client.bootstrap()
    await client.auth_initiate(phone)
    code = input("SMS code: ").strip()
    await client.auth_verify(code)
    try:
        cats = await client.get_category_tree()
        _save("categories.json", cats)
        if cats:
            node = cats[0].node_code
            res = await client.get_category_skus(node, offset=0, limit=24)
            _save("skus_list.json", _raw(res))
            if res.items:
                p = await client.get_product(res.items[0].code)
                _save("product.json", _raw(p))
        sr = await client.search("молоко", offset=0, limit=20)
        _save("search.json", _raw(sr))
        weekly = await client.get_promo_weekly()
        _save("mobilepromo_weekly.json", _raw(weekly))
        crazy = await client.get_promo_crazy()
        _save("crazy_list.json", _raw(crazy))
        if crazy and crazy[0].id:
            detail = await client.get_promo_crazy_detail(crazy[0].id)
            _save("crazy_detail.json", _raw(detail))
        stores = await client._http.get(
            f"/api/v1/cities/{client._store_id and 'spb'}/stores",
            headers=client._request_headers(),
        )
        _save("stores_spb.json", stores.json())
    finally:
        await client.aclose()
    print(f"fixtures dumped to {FIXTURES}")


def _save(name: str, payload) -> None:
    (FIXTURES / name).write_text(
        json.dumps(payload, indent=2, ensure_ascii=False, default=str), encoding="utf-8"
    )
    print(f"  wrote {name}")


def _raw(obj) -> Any:
    if hasattr(obj, "model_dump"):
        try:
            return obj.model_dump(by_alias=True)
        except Exception:
            return obj.model_dump()
    return obj


if __name__ == "__main__":
    asyncio.run(main())