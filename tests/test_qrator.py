from __future__ import annotations

from app.qrator import get_solver


async def test_fake_solver_returns_cookies(fake_solver):
    cookies = await fake_solver.solve()
    assert "qrator_jsid" in cookies
    assert "App_Cache_CitySlug" in cookies


async def test_get_solver_singleton():
    s1 = get_solver()
    s2 = get_solver()
    assert s1 is s2


async def test_cookie_jar_propagates(fake_solver):
    from app.client import LentaClient
    from app.config import settings
    client = LentaClient(solver=fake_solver)
    await client._refresh_qrator()
    assert client._cookies["qrator_jsid"] == "test-qrator"
    assert client._cookies["App_Cache_CitySlug"] == settings.lenta_city_key
    await client.aclose()