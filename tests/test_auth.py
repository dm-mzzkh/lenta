from __future__ import annotations

import pytest

from app.client import LentaAuthError, LentaClient, LentaNotAuthenticated, LentaSessionExpired
from app.config import settings
from app.schemas import AuthState


async def test_init_state_idle(fresh_client: LentaClient):
    assert fresh_client.state == AuthState.idle
    assert fresh_client.auth_status().state == AuthState.idle


async def test_data_method_requires_session(fresh_client: LentaClient):
    with pytest.raises(LentaNotAuthenticated):
        await fresh_client.get_category_tree()


async def test_auth_initiate_sets_awaiting_code(mock_lenta, fresh_client: LentaClient):
    nta = await fresh_client.auth_initiate("79990000000")
    assert nta == "2026-07-06T12:00:00Z"
    assert fresh_client.state == AuthState.awaiting_code
    status = fresh_client.auth_status()
    assert status.state == AuthState.awaiting_code
    assert status.last_try_allowed_at == "2026-07-06T12:00:00Z"


async def test_auth_verify_without_initiate_rejected(mock_lenta, fresh_client):
    with pytest.raises(LentaAuthError, match="call /api/auth/login first"):
        await fresh_client.auth_verify("1234")


async def test_auth_verify_success_sets_logged_in(mock_lenta, fresh_client):
    await fresh_client.auth_initiate("79990000000")
    await fresh_client.auth_verify("1234")
    assert fresh_client.state == AuthState.logged_in
    assert fresh_client._cookies.get("App_Cache_MPK") == "test-session"


async def test_auth_verify_auto_picks_store_when_unset(mock_lenta, fresh_client, monkeypatch):
    monkeypatch.setattr(settings, "lenta_default_store_id", "")
    fresh_client._store_id = ""
    await fresh_client.auth_initiate("79990000000")
    await fresh_client.auth_verify("1234")
    assert fresh_client._store_id == "3550"


async def test_data_methods_work_after_verify(mock_lenta, fresh_client):
    await fresh_client.auth_initiate("79990000000")
    await fresh_client.auth_verify("1234")
    cats = await fresh_client.get_category_tree()
    assert len(cats) == 2


async def test_verify_bad_code_keeps_awaiting(respx_mock, fresh_client: LentaClient):
    respx_mock.post("https://lenta.com/api/v1/authentication/requestValidationCode").respond(
        200, json={"nextTryAllowedAt": "2026-07-06T12:00:00Z"}
    )
    respx_mock.post("https://lenta.com/api/v1/authentication/loginotp").respond(
        401, json={"errorCode": "InvalidCode"}
    )
    await fresh_client.auth_initiate("79990000000")
    with pytest.raises(LentaAuthError, match="rejected code"):
        await fresh_client.auth_verify("9999")
    assert fresh_client.state == AuthState.awaiting_code


async def test_401_on_data_request_raises_session_expired(mock_lenta, fresh_client):
    await fresh_client.auth_initiate("79990000000")
    await fresh_client.auth_verify("1234")
    # Mock the product endpoint response to 401
    mock_lenta.get("/api-gateway/v1/catalog/items/152153").respond(
        401, json={"errorCode": "Unauthorized"}
    )
    with pytest.raises(LentaSessionExpired):
        await fresh_client.get_product("152153")
    # Critical: state is reset to idle to force a human re-login.
    assert fresh_client.state == AuthState.idle


async def test_manual_cookies_login_skips_sms(mock_lenta, fresh_client: LentaClient):
    """Manual cookie mode: session is already logged in in the browser, /verify not needed."""
    cookies = {
        "qrator_jsid": "manual-qrator",
        "App_Cache_MPK": "manual-session",
        "App_Cache_CitySlug": "spb",
    }
    nta = await fresh_client.auth_initiate("79990000000", cookies=cookies)
    assert nta == ""  # no SMS flow
    assert fresh_client.state == AuthState.logged_in
    assert fresh_client._cookies["App_Cache_MPK"] == "manual-session"
    # Data methods work right away.
    cats = await fresh_client.get_category_tree()
    assert len(cats) == 2


async def test_manual_cookies_auto_pick_store(mock_lenta, fresh_client, monkeypatch):
    monkeypatch.setattr(settings, "lenta_default_store_id", "")
    fresh_client._store_id = ""
    cookies = {"qrator_jsid": "manual-q", "App_Cache_MPK": "manual-s"}
    await fresh_client.auth_initiate("79990000000", cookies=cookies)
    assert fresh_client._store_id == "3550"


async def test_manual_cookies_warn_missing(fresh_client: LentaClient):
    """Without qrator_jsid/Utk_DvcGuid/PassportRefreshToken — a warning, not a silent 401."""
    cookies = {"App_Cache_MPK": "s", "Utk_SessionToken": "t", "PassportAccessToken": "p"}
    await fresh_client.auth_initiate("79990000000", cookies=cookies)
    warnings = fresh_client.login_warnings()
    assert any("qrator_jsid" in w for w in warnings)
    assert any("Utk_DvcGuid" in w for w in warnings)


async def test_bootstrap_skips_qrator_when_disabled(fresh_client: LentaClient, monkeypatch):
    monkeypatch.setattr(settings, "lenta_headless", False)
    fresh_client._cookies = {}
    await fresh_client.bootstrap()
    assert "qrator_jsid" not in fresh_client._cookies


async def test_bootstrap_runs_qrator_when_enabled(fresh_client: LentaClient, monkeypatch):
    monkeypatch.setattr(settings, "lenta_headless", True)
    await fresh_client.bootstrap()
    assert fresh_client._cookies.get("qrator_jsid") == "test-qrator"
