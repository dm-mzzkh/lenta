from __future__ import annotations

import json
from urllib.parse import parse_qs

import pytest

pytestmark = pytest.mark.asyncio


def _cart_body(goods: list[dict], total: float = 100.0, positions: int | None = None) -> dict:
    return {
        "CartList": [
            {
                "Goods": goods,
                "TotalCost": total,
                "BaseTotalCost": total,
                "PositionsCount": positions if positions is not None else sum(
                    int(g.get("Quantity", 1)) for g in goods
                ),
            }
        ]
    }


_GOODS = [
    {
        "GoodsItemId": "073015",
        "Name": "Мука MAKFA 2кг",
        "Quantity": 1,
        "Price": 119.99,
        "PriceTotal": 119.99,
        "InStockCount": 10,
        "MaxSaleQuantity": 100,
        "ImageSmallUrl": "http://img/73015.png",
    }
]


def _utk_success(body: dict) -> dict:
    return {"Head": {"Status": "success"}, "Body": body}


async def test_cart_get(app_client, mock_lenta):
    mock_lenta.get("/api-gateway/v1/cart").respond(200, json=_cart_body(_GOODS))
    r = await app_client.get("/api/cart")
    assert r.status_code == 200
    d = r.json()
    assert d["items"][0]["GoodsItemId"] == "073015"
    assert d["items"][0]["Quantity"] == 1
    assert d["PositionsCount"] == 1
    assert d["TotalCost"] == 100.0


async def test_cart_get_out_of_stock_item(app_client, mock_lenta):
    # real lenta.com response: an unavailable item sits in the cart with Quantity=0
    # and ErrorCode="M"; it is not counted in PositionsCount/TotalCost
    dead = {
        "GoodsItemId": "768477",
        "Name": "Ветчина ДРУЖЕНА",
        "Quantity": 0,
        "Price": 178.99,
        "PriceTotal": 0,
        "InStockCount": 0,
        "MaxSaleQuantity": None,
        "ErrorCode": "M",
    }
    mock_lenta.get("/api-gateway/v1/cart").respond(
        200, json=_cart_body([*_GOODS, dead], total=119.99, positions=1)
    )
    r = await app_client.get("/api/cart")
    assert r.status_code == 200
    d = r.json()
    assert d["PositionsCount"] == 1
    assert d["TotalCost"] == 119.99
    assert len(d["items"]) == 2
    assert d["items"][1]["ErrorCode"] == "M"
    assert d["items"][1]["Quantity"] == 0
    assert d["items"][1]["InStockCount"] == 0


async def test_cart_add_sends_utk_envelope(app_client, mock_lenta):
    route = mock_lenta.post("/api/rest/cartItemAdd").respond(
        200, json=_utk_success(_cart_body(_GOODS, total=219.98))
    )
    r = await app_client.post("/api/cart/items", json={"sku_code": "073015", "quantity": 1})
    assert r.status_code == 200
    # form-encoded: request={Head:{...},Body:{...}}
    form = parse_qs(route.calls.last.request.content.decode())
    envelope = json.loads(form["request"][0])
    assert envelope["Head"]["Method"] == "cartItemAdd"
    assert envelope["Head"]["MarketingPartnerKey"] == "test-session"
    assert envelope["Body"]["GoodsItemId"] == "073015"
    assert envelope["Body"]["Quantity"] == 1
    assert envelope["Body"]["Return"] == {"Cart": 1, "Goods": 1}


async def test_cart_set_quantity(app_client, mock_lenta):
    route = mock_lenta.post("/api/rest/cartItemModify").respond(
        200, json=_utk_success(_cart_body([dict(_GOODS[0], Quantity=3)]))
    )
    r = await app_client.put("/api/cart/items/073015", json={"quantity": 3})
    assert r.status_code == 200
    assert r.json()["items"][0]["Quantity"] == 3
    envelope = json.loads(parse_qs(route.calls.last.request.content.decode())["request"][0])
    assert envelope["Body"]["Quantity"] == 3


async def test_cart_remove(app_client, mock_lenta):
    mock_lenta.post("/api/rest/cartItemDelete").respond(
        200, json=_utk_success(_cart_body([]))
    )
    r = await app_client.delete("/api/cart/items/073015")
    assert r.status_code == 200
    assert r.json()["items"] == []


async def test_cart_error_maps_to_502(app_client, mock_lenta):
    mock_lenta.post("/api/rest/cartItemAdd").respond(
        200,
        json={
            "Head": {"Status": "failure"},
            "Body": {"ErrorList": [{"Code": "42", "Description": "Товар не найден"}]},
        },
    )
    r = await app_client.post("/api/cart/items", json={"sku_code": "999999", "quantity": 1})
    assert r.status_code == 502
    assert r.json()["error_code"] == "cart_error"


async def test_cart_requires_session(idle_app_client, mock_lenta):
    r = await idle_app_client.get("/api/cart")
    assert r.status_code == 401
    assert r.json()["error_code"] == "not_authenticated"
