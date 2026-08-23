"""Diagnose Qrator bypass: prints cookies + tries /api/v1/cities.

Run: uv run python scripts/diag_qrator.py
"""
from __future__ import annotations

import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")


async def main() -> None:
    import httpx

    from app.qrator import QratorSolver

    solver = QratorSolver()
    cookies = await solver.solve()
    print("\n=== COOKIES ===")
    for k, v in cookies.items():
        print(f"  {k} = {v[:60]}{'...' if len(v) > 60 else ''}")
    print(f"  total: {len(cookies)}")
    print(f"  qrator_jsid present: {'qrator_jsid' in cookies}")

    if "qrator_jsid" not in cookies:
        print("\n[!] qrator_jsid NOT obtained; bypass didn't work.")
        return

    # Try the actual API request with obtained cookies via httpx.
    print("\n=== PROBE /api/v1/cities through httpx ===")
    from app.config import settings
    headers = {
        "accept": "application/json",
        "user-agent": settings.lenta_user_agent,
        "cookie": "; ".join(f"{k}={v}" for k, v in cookies.items()),
    }
    async with httpx.AsyncClient(base_url=settings.lenta_base_url, http2=True) as c:
        r = await c.get("/api/v1/cities", headers=headers)
        print(f"  status: {r.status_code}")
        print(f"  content-type: {r.headers.get('content-type')}")
        text = r.text
        print(f"  body head: {text[:200]}{'...' if len(text) > 200 else ''}")


if __name__ == "__main__":
    asyncio.run(main())