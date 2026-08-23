from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_lenta_client
from app.schemas import Category, ProductDetail, SearchResult

router = APIRouter(prefix="/api/catalog", tags=["catalog"])


@router.get("/categories", response_model=list[Category])
async def categories(client=Depends(get_lenta_client)) -> list[Category]:
    return await client.get_category_tree()


@router.get("/category/{node_code}", response_model=SearchResult)
async def category_skus(
    node_code: str,
    page: int = Query(1, ge=1),
    size: int = Query(24, ge=1, le=100),
    client=Depends(get_lenta_client),
) -> SearchResult:
    offset = (page - 1) * size
    return await client.get_category_skus(node_code, offset=offset, limit=size)


@router.get("/product/{sku_code}", response_model=ProductDetail)
async def product(sku_code: str, client=Depends(get_lenta_client)) -> ProductDetail:
    return await client.get_product(sku_code)
