from __future__ import annotations

import pytest


async def test_status_route_idle(idle_app_client):
    r = await idle_app_client.get("/api/auth/status")
    assert r.status_code == 200
    assert r.json()["state"] == "idle"


async def test_login_route_sends_code(mock_lenta, app_client):
    r = await app_client.post("/api/auth/login", json={"phone": "79990000000"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "code_sent"
    assert body["next_try_allowed_at"] == "2026-07-06T12:00:00Z"


async def test_verify_route_without_login_401(app_client):
    r = await app_client.post("/api/auth/verify", json={"code": "1234"})
    assert r.status_code == 401
    assert "call /api/auth/login" in r.json()["detail"]


async def test_login_validation(app_client):
    r = await app_client.post("/api/auth/login", json={})
    assert r.status_code == 422


async def test_data_route_502_on_session_expired(mock_lenta, idle_app_client):
    # idle_app_client: singleton in idle without login — a data route returning
    # 401 → 502 is impossible here because _require_session raises
    # LentaNotAuthenticated(401) before any request is made.
    # This test would check post-verify expiry via a mocked 401 route.
    # ponytail: no double state machine in tests; covered at client level.
    pytest.skip("see test_auth.test_401_on_data_request_raises_session_expired")


async def test_data_route_401_when_not_logged_in(idle_app_client):
    r = await idle_app_client.get("/api/catalog/categories")
    assert r.status_code == 401
    body = r.json()
    assert body["error_code"] == "not_authenticated"


async def test_full_auth_flow_then_data_route(mock_lenta, idle_app_client):
    r = await idle_app_client.post("/api/auth/login", json={"phone": "79990000000"})
    assert r.status_code == 202
    r = await idle_app_client.post("/api/auth/verify", json={"code": "1234"})
    assert r.status_code == 200
    assert r.json()["state"] == "logged_in"
    # Data routes should work now.
    r = await idle_app_client.get("/api/catalog/categories")
    assert r.status_code == 200


async def test_manual_cookies_login_route(mock_lenta, idle_app_client):
    """Manual mode: POST /login with cookies → logged_in right away, no /verify."""
    body = {
        "phone": "79990000000",
        "cookies": {
            "qrator_jsid": "m-q",
            "App_Cache_MPK": "m-s",
            "App_Cache_CitySlug": "spb",
        },
    }
    r = await idle_app_client.post("/api/auth/login", json=body)
    assert r.status_code == 202
    assert r.json()["status"] == "manual_session_loaded"
    r = await idle_app_client.get("/api/auth/status")
    assert r.json()["state"] == "logged_in"
    # Data routes work without /verify.
    r = await idle_app_client.get("/api/catalog/categories")
    assert r.status_code == 200