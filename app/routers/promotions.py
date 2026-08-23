from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_lenta_client
from app.schemas import Promotion, PromotionDetail

router = APIRouter(prefix="/api/promotions", tags=["promotions"])


@router.get("/weekly", response_model=list[Promotion])
async def promo_weekly(
    offset: int = Query(0, ge=0),
    limit: int = Query(500, ge=1, le=1000),
    client=Depends(get_lenta_client),
) -> list[Promotion]:
    return await client.get_promo_weekly(offset=offset, limit=limit)


@router.get("/crazy", response_model=list[Promotion])
async def promo_crazy(client=Depends(get_lenta_client)) -> list[Promotion]:
    return await client.get_promo_crazy()


@router.get("/crazy/{promo_id}", response_model=PromotionDetail)
async def promo_crazy_detail(
    promo_id: str, client=Depends(get_lenta_client)
) -> PromotionDetail:
    return await client.get_promo_crazy_detail(promo_id)