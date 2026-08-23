from __future__ import annotations

from fastapi import APIRouter, Depends

from app.deps import get_lenta_client
from app.schemas import CartItemRequest, CartQuantityRequest, CartSummary

router = APIRouter(prefix="/api/cart", tags=["cart"])


@router.get("", response_model=CartSummary)
async def cart_get(client=Depends(get_lenta_client)) -> CartSummary:
    return await client.cart_get()


@router.post("/items", response_model=CartSummary)
async def cart_add(
    item: CartItemRequest, client=Depends(get_lenta_client)
) -> CartSummary:
    return await client.cart_item_add(item.sku_code, item.quantity)


@router.put("/items/{sku_code}", response_model=CartSummary)
async def cart_set_quantity(
    sku_code: str, req: CartQuantityRequest, client=Depends(get_lenta_client)
) -> CartSummary:
    return await client.cart_item_modify(sku_code, req.quantity)


@router.delete("/items/{sku_code}", response_model=CartSummary)
async def cart_remove(sku_code: str, client=Depends(get_lenta_client)) -> CartSummary:
    return await client.cart_item_delete(sku_code)


@router.delete("", response_model=CartSummary)
async def cart_clear(client=Depends(get_lenta_client)) -> CartSummary:
    summary = await client.cart_get()
    for item in summary.items:
        await client.cart_item_delete(item.code)
    return await client.cart_get()
