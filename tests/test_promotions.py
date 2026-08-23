from __future__ import annotations

from app.client import LentaClient
from app.schemas import Promotion, PromotionDetail, PromotionType


async def test_promo_weekly(mock_lenta, lenta_client: LentaClient):
    promos = await lenta_client.get_promo_weekly()
    assert len(promos) == 1
    promo = promos[0]
    assert isinstance(promo, Promotion)
    assert promo.type == PromotionType.weekly
    assert promo.title == "Скидки недели"
    assert promo.items == []


async def test_promo_crazy(mock_lenta, lenta_client):
    promos = await lenta_client.get_promo_crazy()
    assert promos == []


async def test_promo_crazy_detail(mock_lenta, lenta_client):
    detail = await lenta_client.get_promo_crazy_detail("CRAZY001")
    assert isinstance(detail, PromotionDetail)
    assert detail.id == "CRAZY001"
    assert detail.type == PromotionType.crazy
    assert detail.items == []


async def test_promo_weekly_route(mock_lenta, app_client):
    r = await app_client.get("/api/promotions/weekly")
    assert r.status_code == 200
    body = r.json()
    assert body[0]["type"] == "weekly"


async def test_promo_crazy_route(mock_lenta, app_client):
    r = await app_client.get("/api/promotions/crazy")
    assert r.status_code == 200
    assert r.json() == []


async def test_promo_crazy_detail_route(mock_lenta, app_client):
    r = await app_client.get("/api/promotions/crazy/CRAZY001")
    assert r.status_code == 200
    body = r.json()
    assert body["id"] == "CRAZY001"
    assert body["items"] == []
