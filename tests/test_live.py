"""Smoke tests against the real lenta.com. Skipped by default.

Run: uv run pytest -m live --live

Requires a .env with real credentials and playwright+chromium installed.
"""
from __future__ import annotations

import pytest

pytestmark = pytest.mark.live


@pytest.fixture(autouse=True)
def _live_guard(request):
    if request.node.get_closest_marker("live") is None:
        return
    if not request.config.getoption("--live", default=False):
        pytest.skip("live test; pass --live to run")


async def test_live_categories():
    from app.client import LentaClient
    from app.qrator import get_solver

    client = LentaClient(solver=get_solver())
    try:
        await client.bootstrap()
        cats = await client.get_category_tree()
        assert isinstance(cats, list)
        assert len(cats) > 0
    finally:
        await client.aclose()


async def test_live_search_milk():
    from app.client import LentaClient
    from app.qrator import get_solver

    client = LentaClient(solver=get_solver())
    try:
        await client.bootstrap()
        res = await client.search("молоко", offset=0, limit=5)
        assert res.total > 0
        assert len(res.items) > 0
    finally:
        await client.aclose()


async def test_live_promo_weekly():
    from app.client import LentaClient
    from app.qrator import get_solver

    client = LentaClient(solver=get_solver())
    try:
        await client.bootstrap()
        promos = await client.get_promo_weekly()
        assert isinstance(promos, list)
    finally:
        await client.aclose()