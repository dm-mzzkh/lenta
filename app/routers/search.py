from __future__ import annotations

from fastapi import APIRouter, Depends, Query

from app.deps import get_lenta_client
from app.schemas import SearchResult

router = APIRouter(prefix="/api/search", tags=["search"])


@router.get("", response_model=SearchResult)
async def search(
    q: str = Query(..., min_length=1),
    page: int = Query(1, ge=1),
    size: int = Query(20, ge=1, le=100),
    client=Depends(get_lenta_client),
) -> SearchResult:
    offset = (page - 1) * size
    return await client.search(q, offset=offset, limit=size)