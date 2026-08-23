from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import respx

from app.client import LentaClient, set_client_for_tests
from app.config import settings
from app.qrator import set_solver_for_tests


def pytest_addoption(parser):
    parser.addoption(
        "--live", action="store_true", default=False, help="run live tests against lenta.com"
    )


FIXTURES = Path(__file__).parent / "fixtures"


def load(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text(encoding="utf-8"))


def catalog_items_response(request: httpx.Request) -> httpx.Response:
    body = json.loads(request.content or b"{}")
    fixture = "skus_list.json" if "categoryId" in body else "search.json"
    return httpx.Response(200, json=load(fixture))


class _FakeSolver:
    """Does not start Chromium; returns a cookie stub for tests."""

    async def solve(self) -> dict[str, str]:
        return {"qrator_jsid": "test-qrator", "App_Cache_CitySlug": settings.lenta_city_key}


@pytest.fixture(autouse=True)
def _isolated_store(tmp_path):
    """Every test gets a fresh sqlite store; the real data/lenta.db is never touched."""
    from app import store

    store.reset(str(tmp_path / "store.db"))
    yield
    store.reset()


@pytest.fixture
def fixtures_dir() -> Path:
    return FIXTURES


@pytest.fixture
def fake_solver():
    solver = _FakeSolver()
    set_solver_for_tests(solver)
    yield solver
    set_solver_for_tests(None)


@pytest.fixture
async def lenta_client(fake_solver) -> LentaClient:
    """Client in logged_in state for data routes; auth tests set state themselves."""
    from app.schemas import AuthState

    client = LentaClient(solver=fake_solver)
    client._store_id = settings.lenta_default_store_id or "3550"
    client._cookies = {"qrator_jsid": "test-qrator", "App_Cache_MPK": "test-session"}
    client._state = AuthState.logged_in
    set_client_for_tests(client)
    yield client
    await client.aclose()
    set_client_for_tests(None)


@pytest.fixture
async def fresh_client(fake_solver) -> LentaClient:
    """Client in idle state for auth flow tests."""
    client = LentaClient(solver=fake_solver)
    client._store_id = settings.lenta_default_store_id or "3550"
    client._cookies = {"qrator_jsid": "test-qrator"}
    set_client_for_tests(client)
    yield client
    await client.aclose()
    set_client_for_tests(None)


@pytest.fixture
async def app_client(lenta_client):
    """ASGI client over FastAPI; singleton already logged_in (see lenta_client)."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
async def idle_app_client(fresh_client):
    """ASGI client, singleton in idle (qrator only, no login)."""
    from app.main import app

    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
        yield c


@pytest.fixture
def mock_lenta(fixtures_dir):
    with respx.mock(
        base_url=settings.lenta_base_url, assert_all_called=False, assert_all_mocked=False
    ) as router:
        router.post("/api/v1/authentication/requestValidationCode").respond(
            200, json={"nextTryAllowedAt": "2026-07-06T12:00:00Z"}
        )
        router.post("/api/v1/authentication/loginotp").respond(
            200, json={"ok": True}, headers={"set-cookie": "App_Cache_MPK=test-session; Path=/"}
        )
        router.get("/api-gateway/v1/stores/default/alias").respond(200, json={"alias": "3550"})
        router.get("/api-gateway/v1/catalog/categories").respond(200, json=load("categories.json"))
        router.post("/api-gateway/v1/catalog/items").mock(side_effect=catalog_items_response)
        router.get("/api-gateway/v1/catalog/items/73015").respond(200, json=load("product.json"))
        router.get("/api-gateway/v1/pages/actions").respond(
            200, json={"items": [{"pageId": 1, "name": "Скидки недели"}], "total": 1}
        )
        yield router
