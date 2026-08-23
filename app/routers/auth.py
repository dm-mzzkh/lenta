from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.client import LentaAuthError, get_lenta_client
from app.schemas import AuthStatus, LoginRequest, VerifyRequest

router = APIRouter(prefix="/api/auth", tags=["auth"])


@router.get("/status", response_model=AuthStatus)
async def status(client=Depends(get_lenta_client)) -> AuthStatus:
    return client.auth_status()


@router.post("/login", status_code=202)
async def login(body: LoginRequest, client=Depends(get_lenta_client)) -> dict:
    try:
        await client.auth_initiate(body.phone, cookies=body.cookies)
    except LentaAuthError as e:
        raise HTTPException(status_code=502, detail=str(e)) from e
    if body.cookies:
        return {
            "status": "manual_session_loaded",
            "store_id": client.auth_status().store_id,
            "warnings": client.login_warnings(),
        }
    return {"status": "code_sent", "next_try_allowed_at": client.auth_status().last_try_allowed_at}


@router.post("/verify", response_model=AuthStatus)
async def verify(body: VerifyRequest, client=Depends(get_lenta_client)) -> AuthStatus:
    try:
        await client.auth_verify(body.code)
    except LentaAuthError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e
    return client.auth_status()
