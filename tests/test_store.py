from __future__ import annotations

import json

from app import store
from app.client import LentaClient

from .conftest import FIXTURES


def load(name: str) -> dict:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def rows(sql: str, *args: object) -> list[dict]:
    return [dict(r) for r in store._db().execute(sql, args).fetchall()]


def test_cache_roundtrip_and_ttl():
    store.cache_put("k", '{"a": 1}')
    assert store.cache_get("k", 600) == '{"a": 1}'
    store._db().execute("UPDATE cache SET stored_at = 0")
    assert store.cache_get("k", 600) is None


def test_session_roundtrip():
    store.save_session({"qrator_jsid": "x"}, {"state": "logged_in", "store_id": "3550"})
    sess = store.load_session()
    assert sess is not None
    assert sess["cookies"]["qrator_jsid"] == "x"
    assert sess["store_id"] == "3550"
    store.clear_session()
    assert store.load_session() is None


def test_observe_first_delta_and_dedup():
    store.observe([("80424", {"title": "Молоко", "price": 7999, "discount": 7499, "stock": 18})])
    first = rows("SELECT field, old, new FROM changes")
    assert {(r["field"], r["old"], r["new"]) for r in first} == {
        ("title", None, "Молоко"),
        ("price", None, "7999"),
        ("discount", None, "7499"),
        ("stock", None, "18"),
    }

    # identical observation → no new changes
    store.observe([("80424", {"title": "Молоко", "price": 7999, "discount": 7499, "stock": 18})])
    assert len(rows("SELECT * FROM changes")) == 4

    # price up, discount removed
    store.observe([("80424", {"price": 9899, "discount": None})])
    deltas = rows("SELECT field, old, new FROM changes ORDER BY ts DESC, field LIMIT 2")
    assert {(r["field"], r["old"], r["new"]) for r in deltas} == {
        ("price", "7999", "9899"),
        ("discount", "7499", None),
    }

    # sparse observation does not clobber known fields
    store.observe([("80424", {"price": 9899})])
    p = rows("SELECT * FROM products WHERE sku='80424'")[0]
    assert p["title"] == "Молоко" and p["price"] == 9899 and p["discount"] is None


def test_observe_batch_single_commit():
    store.observe([
        ("1", {"title": "A", "price": 100}),
        ("2", {"title": "B", "price": 200}),
    ])
    assert len(rows("SELECT * FROM products")) == 2
    assert len(rows("SELECT * FROM changes")) == 4


def test_extract_item_formats():
    # old fixture format (rubles, str stock)
    old = {
        "code": "123",
        "title": "Чай",
        "regularPrice": 100.0,
        "discountPrice": 80.0,
        "stock": "5",
    }
    item = store.extract_item(old)
    assert item is not None
    sku, fields = item
    assert sku == "123"
    assert fields["price"] == 10000 and fields["discount"] == 8000 and fields["stock"] == 5

    # new gateway format (kopecks, count, display, attributes)
    card = load("product.json")
    item = store.extract_item(card)
    assert item is not None
    sku, fields = item
    assert sku == str(card["id"])
    assert fields["price"] == 16849 and fields["discount"] == 12499
    assert fields["stock"] == 100 and fields["brand"] == "MAKFA"
    assert fields["title"].startswith("Мука")


async def test_client_search_caches_and_observes(lenta_client: LentaClient, mock_lenta):
    r1 = await lenta_client.search("молоко")
    calls_after_first = len(mock_lenta.calls)
    assert r1.items

    r2 = await lenta_client.search("молоко")
    assert len(mock_lenta.calls) == calls_after_first  # second call served from cache
    assert r2.total == r1.total

    assert rows("SELECT COUNT(*) c FROM cache")[0]["c"] >= 1
    assert rows("SELECT COUNT(*) c FROM products")[0]["c"] >= 1


async def test_client_product_observes_and_caches(lenta_client: LentaClient, mock_lenta):
    p1 = await lenta_client.get_product("73015")
    calls_after_first = len(mock_lenta.calls)
    p2 = await lenta_client.get_product("73015")
    assert len(mock_lenta.calls) == calls_after_first
    assert p1.code == p2.code

    p = rows("SELECT title, brand, price FROM products WHERE sku=?", p1.code)[0]
    assert p["brand"] == "MAKFA"
    assert p["price"] == 16849


async def test_session_restore_after_restart(fake_solver):
    """uvicorn --reload must not kill the login: bootstrap() rehydrates from sqlite."""
    from app.schemas import AuthState

    store.save_session(
        {"qrator_jsid": "db-qrator", "App_Cache_MPK": "db-mpk"},
        {"state": "logged_in", "store_id": "3550"},
    )
    client = LentaClient(solver=fake_solver)
    await client.bootstrap()
    try:
        assert client.state == AuthState.logged_in
        assert client._cookies["qrator_jsid"] == "db-qrator"
        assert client.store_id == "3550"
    finally:
        await client.aclose()


async def test_db_history_route(mock_lenta, app_client):
    await app_client.get("/api/catalog/product/73015")  # observes MAKFA flour
    r = await app_client.get("/api/db/history/73015")
    assert r.status_code == 200
    d = r.json()
    assert d["title"].startswith("Мука")
    assert d["price"] == 16849
    assert d["min_price"] == 16849 and d["max_price"] == 16849
    assert any(c["field"] == "brand" for c in d["changes"])

    r404 = await app_client.get("/api/db/history/999999")
    assert r404.status_code == 404
