from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

import httpx

from app import store
from app.config import settings
from app.parsing import (
    cart_from_api,
    detail_from_api,
    parse_category_tree,
    promo_from_action,
    search_result_from,
)
from app.qrator import get_solver
from app.schemas import (
    AuthState,
    AuthStatus,
    CartError,
    CartSummary,
    Category,
    ProductDetail,
    Promotion,
    PromotionDetail,
    PromotionType,
    SearchResult,
)

log = logging.getLogger("lenta.client")

# Manual mode does not work without these cookies: qrator_jsid passes the WAF (401),
# Utk_DvcGuid is needed for deviceid (400), PassportRefreshToken — for auto-refresh.
_MANUAL_COOKIES = (
    "App_Cache_MPK",
    "Utk_SessionToken",
    "PassportAccessToken",
    "qrator_jsid",
    "Utk_DvcGuid",
    "PassportRefreshToken",
)


class LentaAuthError(Exception):
    """Cannot start a session (wrong code, SMS service unavailable, etc.)."""


class LentaNotAuthenticated(Exception):
    """Service is not logged in — /api/auth/login has not been called yet."""


class LentaSessionExpired(Exception):
    """Lenta returned 401 on a data request — session expired, re-login needed."""

    def __init__(self, path: str) -> None:
        super().__init__(f"session expired on {path}; call /api/auth/login again")
        self.path = path


# ponytail: one client class, no interface/factory — the only implementation.
class LentaClient:
    def __init__(self, solver: Any | None = None) -> None:
        self._solver = solver or get_solver()
        self._cookies: dict[str, str] = {}
        self._store_id: str = settings.lenta_default_store_id
        self._state: AuthState = AuthState.idle
        self._phone: str | None = None
        self._next_try_allowed_at: str | None = None
        self._login_warnings: list[str] = []
        self._auth_lock = asyncio.Lock()
        self._http = httpx.AsyncClient(
            base_url=settings.lenta_base_url,
            timeout=settings.lenta_timeout,
            follow_redirects=True,
            headers=self._base_headers(),
            http2=True,
        )

    # ---------- headers / cookies ----------

    def _base_headers(self) -> dict[str, str]:
        return {
            "accept": "application/json",
            "accept-language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "client": "angular_web_0.0.2",
            "content-type": "application/json",
            "x-platform": "omniweb",
            "x-retail-brand": "lo",
            "x-domain": settings.lenta_city_key,
            "x-delivery-mode": "pickup",
            "x-device-os": "Web",
            "x-device-os-version": "12.4.8",
            "x-device-id": settings.lenta_device_id,
            "deviceid": settings.lenta_device_id,
            "x-user-session-id": settings.lenta_session_id,
            "user-agent": settings.lenta_user_agent,
            "origin": settings.lenta_base_url,
            "referer": f"{settings.lenta_base_url}/catalog/",
            "sec-ch-ua": '"Google Chrome";v="127","Not.A/Brand";v="8","Chromium";v="127"',
            "sec-ch-ua-mobile": "?0",
            "sec-ch-ua-platform": '"Windows"',
            "sec-fetch-dest": "empty",
            "sec-fetch-mode": "cors",
            "sec-fetch-site": "same-origin",
        }

    def _cookie_header(self) -> str:
        # App_Cache_MissionAddressMode carries storeId; App_Cache_CitySlug — the city.
        extra = ""
        if self._store_id:
            mission = {
                "t": "pickup",
                "ids": True,
                "ma": {
                    "i": int(self._store_id) if self._store_id.isdigit() else self._store_id,
                    "a": self._store_id.zfill(4),
                    "t": "",
                    "ri": 1,
                    "mt": "HM",
                    "s": False,
                },
            }
            extra = f"; App_Cache_MissionAddressMode={json.dumps(mission, separators=(',', ':'))}"
            extra += f"; App_Cache_CitySlug={settings.lenta_city_key}"
        return "; ".join(f"{k}={v}" for k, v in self._cookies.items()) + extra

    def _merge_cookies(self, set_cookie: str | None) -> None:
        if not set_cookie:
            return
        for part in set_cookie.split(","):
            if "=" not in part:
                continue
            name, _, value = part.partition("=")
            name = name.strip().split()[-1] if name.strip() else name.strip()
            if not name:
                continue
            self._cookies[name] = value.strip().split(";")[0]
        self._persist_session()

    def _persist_session(self) -> None:
        """Save cookies + auth state to sqlite, so --reload / restarts survive."""
        if self._state != AuthState.logged_in:
            return
        try:
            store.save_session(
                self._cookies, {"state": self._state.value, "store_id": self._store_id}
            )
        except Exception as e:
            log.warning("session persist failed: %s", e)

    def _restore_session(self) -> None:
        try:
            sess = store.load_session()
        except Exception as e:
            log.warning("session restore failed: %s", e)
            return
        if not sess or sess.get("state") != "logged_in":
            return
        self._cookies.update(sess.get("cookies") or {})
        self._state = AuthState.logged_in
        if sess.get("store_id"):
            self._store_id = sess["store_id"]
        log.info(
            "session restored from db (%d cookies, store=%s)", len(self._cookies), self._store_id
        )

    def _drop_session(self) -> None:
        try:
            store.clear_session()
        except Exception as e:
            log.warning("session clear failed: %s", e)

    def _request_headers(self) -> dict[str, str]:
        h = self._base_headers()
        h["cookie"] = self._cookie_header()
        # ponytail: Lenta validates deviceid against the Utk_DvcGuid cookie —
        # a mismatch gives 400 BAD_REQUEST on all data requests.
        device = self._cookies.get("Utk_DvcGuid") or settings.lenta_device_id
        h["deviceid"] = device
        h["x-device-id"] = device
        if "Utk_SessionToken" in self._cookies:
            h["sessiontoken"] = self._cookies["Utk_SessionToken"]
        if "PassportAccessToken" in self._cookies:
            h["passportaccesstoken"] = self._cookies["PassportAccessToken"]
            h["authorization"] = f"Bearer {self._cookies['PassportAccessToken']}"
        return h

    # ---------- lifecycle ----------

    async def aclose(self) -> None:
        await self._http.aclose()

    async def bootstrap(self) -> None:
        """Startup: pass Qrator. No login here — SMS code is entered manually.

        ponytail: headless-qrator only runs when LENTA_HEADLESS=true.
        Default is manual cookie mode: the user supplies their own qrator_jsid,
        and an extra headless pass can rotate/burn the challenge and break the session.
        """
        if not settings.lenta_headless:
            log.info("qrator solver disabled (LENTA_HEADLESS=false); manual cookies mode")
            self._restore_session()
            return
        async with self._auth_lock:
            await self._refresh_qrator()
        self._restore_session()

    async def _refresh_qrator(self) -> None:
        try:
            cookies = await self._solver.solve()
            self._cookies.update(cookies)
            log.info("qrator cookies merged (%d total)", len(self._cookies))
        except Exception as e:
            log.warning("qrator solve failed: %s", e)

    # ---------- auth (SMS-OTP) ----------

    @property
    def state(self) -> AuthState:
        return self._state

    @property
    def store_id(self) -> str | None:
        return self._store_id or None

    def auth_status(self) -> AuthStatus:
        return AuthStatus(
            state=self._state,
            store_id=self._store_id or None,
            last_try_allowed_at=self._next_try_allowed_at,
        )

    async def auth_initiate(self, phone: str, cookies: dict[str, str] | None = None) -> str:
        """Step 1.

        - With `cookies` (manual mode, for when Qrator blocks headless): merge
          browser DevTools cookies, treat the session as already logged in,
          set logged_in. Data routes work immediately. Step 2 (verify) is not needed.
        - Otherwise: POST requestValidationCode → Lenta sends an SMS. Returns nextTryAllowedAt.

        Returns ``""`` in manual mode, ``nextTryAllowedAt`` otherwise.
        """
        self._login_warnings = []
        async with self._auth_lock:
            if cookies:
                self._cookies.update(cookies)
                self._phone = phone
                self._state = AuthState.logged_in
                self._next_try_allowed_at = None
                missing = [k for k in _MANUAL_COOKIES if k not in cookies]
                if missing:
                    msg = (
                        "manual login: missing required cookies: "
                        f"{', '.join(missing)}. Without them data requests will return "
                        "401 (qrator_jsid) / 400 (Utk_DvcGuid) / 502 (PassportRefreshToken)."
                    )
                    log.warning(msg)
                    self._login_warnings.append(msg)
                log.info("manual cookies accepted (%d), skipping SMS flow", len(cookies))
                if not self._store_id:
                    store = self._parse_store_from_mission()
                    if not store:
                        try:
                            store = await self._pick_default_store()
                        except Exception as e:
                            log.warning("store detection failed: %s", e)
                    if store:
                        self._store_id = store
                self._persist_session()
                return ""
            self._phone = phone
            resp = await self._http.post(
                "/api/v1/authentication/requestValidationCode",
                json={"phoneNumber": phone},
                headers=self._request_headers(),
            )
            if resp.status_code != 200:
                raise LentaAuthError(
                    f"requestValidationCode failed: {resp.status_code} {resp.text[:200]}"
                )
            data = resp.json() if resp.content else {}
            self._next_try_allowed_at = data.get("nextTryAllowedAt")
            self._state = AuthState.awaiting_code
            log.info("SMS code requested for %s; next_try=%s", phone, self._next_try_allowed_at)
            return self._next_try_allowed_at or ""

    def login_warnings(self) -> list[str]:
        return list(self._login_warnings)

    async def auth_verify(self, code: str) -> None:
        """Step 2: POST loginotp → save the session. On success — pick store if unset."""
        async with self._auth_lock:
            if self._state != AuthState.awaiting_code or not self._phone:
                raise LentaAuthError("call /api/auth/login first")
            resp = await self._http.post(
                "/api/v1/authentication/loginotp",
                json={
                    "phoneNumber": self._phone,
                    "otp": code,
                    "verificationCode": code,
                },
                headers=self._request_headers(),
            )
            self._merge_cookies(resp.headers.get("set-cookie"))
            if resp.status_code != 200:
                # Wrong code → stay in awaiting_code, another request is allowed.
                log.warning("verify failed: %s %s", resp.status_code, resp.text[:200])
                raise LentaAuthError(
                    f"loginotp rejected code: {resp.status_code} {resp.text[:200]}"
                )
            self._state = AuthState.logged_in
            log.info("logged in via OTP, phone=%s", self._phone)
            if not self._store_id:
                self._store_id = (await self._pick_default_store()) or ""
            self._persist_session()

    def _parse_store_from_mission(self) -> str | None:
        if self._store_id:
            return self._store_id
        try:
            raw = self._cookies.get("App_Cache_MissionAddressMode", "")
            if raw.startswith("%"):
                import urllib.parse

                raw = urllib.parse.unquote(raw)
            if raw.startswith("{"):
                import json as _json

                mission = _json.loads(raw)
                store = mission.get("ma", {}).get("a") or ""
                if store:
                    log.info("store_id from mission cookie: %s", store)
                    return store.zfill(4)
        except Exception as e:
            log.debug("parse mission cookie failed: %s", e)
        return None

    async def _pick_default_store(self) -> str | None:
        resp = await self._http.get(
            "/api-gateway/v1/stores/default/alias",
            params={"citySlug": settings.lenta_city_key},
            headers=self._request_headers(),
        )
        resp.raise_for_status()
        store = str(resp.json().get("alias") or "")
        if not store:
            log.warning("no default store alias for city=%s", settings.lenta_city_key)
            return None
        log.info("auto-picked store_id=%s for city=%s", store, settings.lenta_city_key)
        return store

    def _require_session(self) -> None:
        if self._state != AuthState.logged_in:
            raise LentaNotAuthenticated(
                f"lenta session not active (state={self._state.value}); "
                "call POST /api/auth/login then POST /api/auth/verify"
            )

    # ---------- token refresh ----------

    async def _refresh_token(self) -> bool:
        refresh = self._cookies.get("PassportRefreshToken")
        if not refresh:
            log.warning("no PassportRefreshToken, cannot refresh")
            return False
        headers = {
            "accept": "application/json",
            "content-type": "application/json",
            "x-platform": "omniweb",
            "x-retail-brand": "lo",
            "cookie": f"PassportRefreshToken={refresh}",
        }
        try:
            resp = await self._http.post(
                "https://api.lenta.com/v1/auth/passport/token/refresh",
                json={"refreshPassportTokenRequest": {}},
                headers=headers,
            )
            if resp.is_success:
                data = resp.json()
                token = data.get("accessToken") or data.get("access_token") or ""
                if token:
                    self._cookies["PassportAccessToken"] = token
                    log.info("token refreshed")
                    self._persist_session()
                    return True
                log.warning("refresh response has no accessToken: %s", resp.text[:200])
            else:
                log.warning("refresh failed: %s %s", resp.status_code, resp.text[:200])
        except Exception as e:
            log.warning("refresh exception: %s", e)
        return False

    # ---------- core request: 401 → refresh + retry, then SessionExpired ----------

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, Any] | None = None,
        json_body: dict | None = None,
    ) -> httpx.Response:
        h = self._request_headers() if not path.startswith("http") else {}
        resp = await self._http.request(method, path, params=params, json=json_body, headers=h)
        if resp.status_code == 401:
            refreshed = await self._refresh_token()
            if refreshed:
                h2 = self._request_headers()
                resp = await self._http.request(
                    method, path, params=params, json=json_body, headers=h2
                )
                if resp.is_success:
                    return resp
            self._state = AuthState.idle
            self._drop_session()
            raise LentaSessionExpired(path)
        return resp

    # ---------- public data methods ----------

    async def _cached_json(self, key: str, ttl: float, fetch) -> Any:
        """Raw-JSON cache layer; `fetch` runs (and observes) only on miss."""
        body = store.cache_get(key, ttl)
        if body is not None:
            log.debug("cache hit: %s", key)
            return json.loads(body)
        data = await fetch()
        try:
            store.cache_put(key, json.dumps(data, ensure_ascii=False))
        except (TypeError, ValueError) as e:
            log.warning("cache put failed for %s: %s", key, e)
        return data

    async def _fetch_category_tree(self) -> Any:
        resp = await self._request("GET", "/api-gateway/v1/catalog/categories")
        resp.raise_for_status()
        return resp.json()

    async def get_category_tree(self) -> list[Category]:
        self._require_session()
        data = await self._cached_json(
            "cat_tree", settings.lenta_cache_ttl_tree, self._fetch_category_tree
        )
        return parse_category_tree(data)

    async def _fetch_items(self, body: dict) -> Any:
        """POST /catalog/items (search or category browse) + observe items."""
        resp = await self._request("POST", "/api-gateway/v1/catalog/items", json_body=body)
        resp.raise_for_status()
        data = resp.json()
        raw_items = data.get("items") or data.get("skus") or []
        store.observe([store.extract_item(s) for s in raw_items if isinstance(s, dict)])
        return data

    def _search_result_from(self, data: dict, offset: int, limit: int) -> SearchResult:
        return search_result_from(data, offset, limit)

    async def get_category_skus(
        self, node_code: str, offset: int = 0, limit: int = 24
    ) -> SearchResult:
        self._require_session()
        key = f"cat:{node_code}|{offset}|{limit}"
        body = {
            "offset": offset,
            "limit": limit,
            "categoryId": int(node_code) if node_code.isdigit() else node_code,
        }
        data = await self._cached_json(
            key, settings.lenta_cache_ttl_search, lambda: self._fetch_items(body)
        )
        return self._search_result_from(data, offset, limit)

    async def _fetch_product(self, sku_code: str) -> Any:
        resp = await self._request("GET", f"/api-gateway/v1/catalog/items/{sku_code}")
        resp.raise_for_status()
        data = resp.json()
        if isinstance(data, dict):
            store.observe([store.extract_item(data)])
        return data

    async def get_product(self, sku_code: str) -> ProductDetail:
        self._require_session()
        data = await self._cached_json(
            f"product:{sku_code}",
            settings.lenta_cache_ttl_product,
            lambda: self._fetch_product(sku_code),
        )
        return detail_from_api(data)

    async def search(self, query: str, offset: int = 0, limit: int = 20) -> SearchResult:
        self._require_session()
        key = f"search:{query}|{offset}|{limit}"
        body = {"query": query, "offset": offset, "limit": limit}
        data = await self._cached_json(
            key, settings.lenta_cache_ttl_search, lambda: self._fetch_items(body)
        )
        return self._search_result_from(data, offset, limit)

    # ---------- cart (legacy UTK /api/rest + gateway GET) ----------

    async def _utk_request(self, method: str, body: dict) -> dict:
        """POST /api/rest/{method} form-encoded.

        ponytail: gateway headers (x-domain/authorization/sessiontoken) break
        the request here (empty ErrorList Code 0) — UTK endpoints want only
        cookies + SessionToken/Domain inside Head. Captured from a real browser.
        """
        self._require_session()
        head = {
            "MarketingPartnerKey": self._cookies.get("App_Cache_MPK", ""),
            "Version": "web-12.0.766",
            "Client": "angular_web_0.0.2",
            "Method": method,
            "RequestId": f"{method}_{uuid.uuid4().hex[:13]}",
            "DeviceId": self._cookies.get("Utk_DvcGuid", ""),
            "Domain": self._cookies.get("App_Cache_CitySlug", settings.lenta_city_key),
            "SessionToken": self._cookies.get("Utk_SessionToken", ""),
        }
        headers = {
            "accept": "application/json, text/plain, */*",
            "content-type": "application/x-www-form-urlencoded",
            "x-retail-brand": "lo",
            "x-device-web-platform": "desktop_web",
            "user-agent": settings.lenta_user_agent,
            "cookie": self._cookie_header(),
        }
        payload = {"request": json.dumps({"Head": head, "Body": body})}
        resp = await self._http.post(f"/api/rest/{method}", data=payload, headers=headers)
        if resp.status_code == 401:
            self._state = AuthState.idle
            raise LentaSessionExpired(f"/api/rest/{method}")
        data = resp.json() if resp.content else {}
        if (data.get("Head") or {}).get("Status") != "success":
            errors = (data.get("Body") or {}).get("ErrorList") or []
            msgs = "; ".join(
                f"{e.get('Description') or e.get('Message') or e.get('Code')}" for e in errors
            ) or f"HTTP {resp.status_code}"
            raise CartError(f"{method} failed: {msgs}")
        return data.get("Body") or {}

    async def cart_get(self) -> CartSummary:
        self._require_session()
        resp = await self._request("GET", "/api-gateway/v1/cart")
        resp.raise_for_status()
        return cart_from_api(resp.json())

    async def cart_item_add(self, sku_code: str, quantity: float = 1) -> CartSummary:
        body = await self._utk_request(
            "cartItemAdd",
            {"GoodsItemId": sku_code, "Quantity": quantity, "Return": {"Cart": 1, "Goods": 1}},
        )
        return cart_from_api(body)

    async def cart_item_modify(self, sku_code: str, quantity: float) -> CartSummary:
        body = await self._utk_request(
            "cartItemModify",
            {
                "GoodsItemId": sku_code,
                "Quantity": quantity,
                "Return": {"Cart": 1, "Goods": 1, "ShowCartItemModifyNotices": 1},
            },
        )
        return cart_from_api(body)

    async def cart_item_delete(self, sku_code: str) -> CartSummary:
        body = await self._utk_request(
            "cartItemDelete",
            {"GoodsItemId": sku_code, "Return": {"Cart": 1, "Goods": 1}},
        )
        return cart_from_api(body)

    async def get_promo_weekly(self, offset: int = 0, limit: int = 500) -> list[Promotion]:
        self._require_session()

        async def _fetch() -> Any:
            resp = await self._request(
                "GET",
                "/api-gateway/v1/pages/actions",
                params={"limit": limit, "offset": offset},
            )
            resp.raise_for_status()
            return resp.json()

        data = await self._cached_json(
            f"promo:weekly|{offset}|{limit}", settings.lenta_cache_ttl_promo, _fetch
        )
        return [promo_from_action(s, PromotionType.weekly) for s in data.get("items", [])]

    async def get_promo_crazy(self) -> list[Promotion]:
        self._require_session()
        # ponytail: current API returns 400 "Метод не поддерживается"
        # ("method not supported") for stores/crazy.
        return []

    async def get_promo_crazy_detail(self, promo_id: str) -> PromotionDetail:
        self._require_session()
        return PromotionDetail(id=str(promo_id), type=PromotionType.crazy, items=[])



# ---------- FastAPI dependency ----------

_client: LentaClient | None = None
_client_lock = asyncio.Lock()


async def get_lenta_client() -> LentaClient:
    global _client
    if _client is None:
        async with _client_lock:
            if _client is None:
                client = LentaClient()
                try:
                    await client.bootstrap()
                except Exception as e:
                    log.error("bootstrap failed: %s", e)
                _client = client
    return _client


def set_client_for_tests(client: LentaClient | None) -> None:
    global _client
    _client = client


async def close_client() -> None:
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None
