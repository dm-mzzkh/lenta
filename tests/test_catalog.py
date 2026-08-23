from __future__ import annotations

import pytest

from app.client import LentaClient
from app.schemas import Category, ProductDetail, SearchResult


async def test_categories(mock_lenta: pytest.fixture, lenta_client: LentaClient):
    cats = await lenta_client.get_category_tree()
    assert len(cats) == 2
    assert isinstance(cats[0], Category)
    assert cats[0].name == "Продукты"
    assert cats[0].node_code == "a1b2c3"
    assert len(cats[0].children) == 2


async def test_category_skus(mock_lenta, lenta_client):
    res = await lenta_client.get_category_skus("a1b2c3", offset=0, limit=24)
    assert isinstance(res, SearchResult)
    assert res.total == 27735
    assert len(res.items) == 1
    p = res.items[0]
    assert p.code == "152153"
    assert p.regular_price == 671.49
    assert p.discount_price == 637.89
    assert p.promo_type == "PromoByCard"
    assert p.categories is not None
    assert p.categories.category["name"] == "Молоко"


async def test_product_detail(mock_lenta, lenta_client):
    p = await lenta_client.get_product("73015")
    assert isinstance(p, ProductDetail)
    assert p.code == "73015"
    assert p.article == "073015"
    assert p.slug == "muka-vs-rossiya-2kg"
    assert p.web_url == "https://lenta.com/product/muka-vs-rossiya-2kg-73015/"
    assert p.brand == "MAKFA"
    assert p.regular_price == 168.49
    assert p.discount_price == 124.99
    assert p.unit == "шт"
    assert [c.name for c in p.category_tree] == [
        "Макароны, крупы, мука",
        "Мука, смеси для выпечки",
        "Мука",
    ]
    assert p.category_tree[0].id == 25
    assert p.nutrition is not None
    assert p.nutrition.proteins == 12.0
    assert p.nutrition.fats == 1.1
    assert p.nutrition.carbs == 70.6
    assert p.nutrition.calories == "340 кКал/1424 кДж"
    assert p.ingredients == "Мука пшеничная хлебопекарная высшего сорта."
    assert len(p.characteristics) == 19
    assert p.description


async def test_categories_route(mock_lenta, app_client):
    r = await app_client.get("/api/catalog/categories")
    assert r.status_code == 200
    data = r.json()
    assert isinstance(data, list)
    assert data[0]["name"] == "Продукты"


async def test_category_route_pagination(mock_lenta, app_client):
    r = await app_client.get("/api/catalog/category/a1b2c3?page=2&size=10")
    assert r.status_code == 200
    body = r.json()
    assert body["limit"] == 10
    assert body["offset"] == 10


async def test_product_route(mock_lenta, app_client):
    r = await app_client.get("/api/catalog/product/73015")
    assert r.status_code == 200
    body = r.json()
    assert body["code"] == "73015"
    assert body["article"] == "073015"
    assert body["slug"] == "muka-vs-rossiya-2kg"
    assert body["regularPrice"] == 168.49
    assert body["category_tree"][0]["name"] == "Макароны, крупы, мука"
    assert body["nutrition"]["proteins"] == 12.0
    assert body["ingredients"].startswith("Мука")


async def test_product_404_passthrough(mock_lenta, lenta_client):
    mock_lenta.get("/api-gateway/v1/catalog/items/MISSING").respond(
        404, json={"message": "not found"}
    )
    import httpx

    with pytest.raises(httpx.HTTPStatusError):
        await lenta_client.get_product("MISSING")


async def test_product_route_404(mock_lenta, app_client):
    """Route level: a 404 from lenta must not turn into a 500."""
    mock_lenta.get("/api-gateway/v1/catalog/items/MISSING").respond(
        404, json={"message": "not found"}
    )
    r = await app_client.get("/api/catalog/product/MISSING")
    assert r.status_code == 404
    assert r.json()["error_code"] == "upstream_error"
