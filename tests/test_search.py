from __future__ import annotations

import respx

from app.client import LentaClient
from app.config import settings
from app.schemas import SearchResult
from tests.conftest import load


async def test_search(mock_lenta, lenta_client: LentaClient):
    res = await lenta_client.search("молоко", offset=0, limit=20)
    assert isinstance(res, SearchResult)
    assert res.total == 2
    assert res.items[0].code == "152153"
    assert res.items[1].code == "987654"


async def test_search_new_api_format(lenta_client: LentaClient):
    """Real 2026 web API format: id/slug/display/prices(kopecks)."""
    with respx.mock(base_url=settings.lenta_base_url, assert_all_called=False) as router:
        router.post("/api-gateway/v1/catalog/items").respond(200, json=load("search_live.json"))
        res = await lenta_client.search("мука")
    assert res.total == 60
    first = res.items[0]
    assert first.code == "73012"
    assert first.title == "Мука пшеничная MAKFA хлебопекарная высший сорт"
    assert first.regular_price == 79.99
    assert first.discount_price == 62.99


async def test_search_pagination_slice(mock_lenta, lenta_client):
    res = await lenta_client.search("молоко", offset=1, limit=1)
    assert res.offset == 1
    assert len(res.items) == 1
    assert res.items[0].code == "987654"


async def test_search_route(mock_lenta, app_client):
    r = await app_client.get("/api/search?q=молоко")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 2
    assert body["items"][0]["code"] == "152153"


async def test_search_route_missing_q(app_client):
    r = await app_client.get("/api/search")
    assert r.status_code == 422
