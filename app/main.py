from __future__ import annotations

import logging
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse

from app.client import LentaNotAuthenticated, LentaSessionExpired, close_client
from app.routers import auth, cart, catalog, db, promotions, search
from app.schemas import CartError

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Do not start QratorSolver on startup — Lenta blocks it in headless mode.
    # LentaClient is created lazily on first use (lazy singleton). The user
    # loads a session via POST /api/auth/login {cookies: ...} or the SMS flow.
    yield
    await close_client()


app = FastAPI(
    title="lenta-proxy",
    description="HTTPS API proxy over lenta.com (catalog / search / promotions, SMS-OTP auth)",
    version="0.1.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(auth.router)
app.include_router(catalog.router)
app.include_router(cart.router)
app.include_router(search.router)
app.include_router(promotions.router)
app.include_router(db.router)


@app.exception_handler(LentaNotAuthenticated)
async def _not_auth_handler(req: Request, exc: LentaNotAuthenticated) -> JSONResponse:
    return JSONResponse(
        status_code=401,
        content={"detail": str(exc), "error_code": "not_authenticated"},
    )


@app.exception_handler(LentaSessionExpired)
async def _expired_handler(req: Request, exc: LentaSessionExpired) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc), "error_code": "session_expired"},
    )


@app.exception_handler(CartError)
async def _cart_error_handler(req: Request, exc: CartError) -> JSONResponse:
    return JSONResponse(
        status_code=502,
        content={"detail": str(exc), "error_code": "cart_error"},
    )


@app.exception_handler(httpx.HTTPStatusError)
async def _upstream_error_handler(req: Request, exc: httpx.HTTPStatusError) -> JSONResponse:
    code = exc.response.status_code
    return JSONResponse(
        status_code=code,
        content={"detail": f"lenta upstream error: {code}", "error_code": "upstream_error"},
    )


@app.get("/health", tags=["meta"])
async def health() -> dict[str, str]:
    return {"status": "ok"}
