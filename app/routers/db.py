from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from app import store

router = APIRouter(prefix="/api/db", tags=["db"])


@router.get("/history/{sku_code}")
async def history(sku_code: str, limit: int = Query(50, ge=1, le=200)) -> dict:
    """Observation history for a SKU: current state, field deltas, min/max price."""
    d = store.history(sku_code, limit)
    if d is None:
        raise HTTPException(404, f"SKU {sku_code} was never observed")
    return d
