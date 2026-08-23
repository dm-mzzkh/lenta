# lenta-proxy

FastAPI wrapper over the lenta.com web API: catalog, search, promotions.
Normalizes responses into clean Pydantic schemas.

> **Qrator WAF blocks headless Chromium** (tested: playwright-chromium,
> playwright-firefox, headed, stealth, playwright-stealth, pauses). So the MVP
> runs in **manual cookie mode**: you open lenta.com in your regular browser
> (or incognito), log in, copy the session cookies, and hand them to the
> service over HTTP. The SMS-OTP flow remains in the code, but without a
> Qrator bypass it does not work (Lenta returns 403 on requestValidationCode).

## Running

```bash
uv sync
uv run playwright install chromium   # for a future Qrator bypass (optional now)
uv run uvicorn app.main:app --reload
```

## Authorization (manual cookie mode)

Step 1. Open lenta.com in Firefox/Chrome (incognito is fine) and log in via the site.

Step 2. Open DevTools → Application (Storage) → Cookies → `https://lenta.com`

Step 3. Find these cookies in DevTools → Application (Storage) → Cookies → `https://lenta.com`:
   - **`App_Cache_MPK`** — session (required)
   - **`PassportAccessToken`** — Bearer token for data requests (required)
   - **`Utk_SessionToken`** — the `sessiontoken` header (required)
   - **`Utk_DvcGuid`** — the `deviceid` header; a mismatch with the session gives 400 on data requests (required)
   - `qrator_jsid` — Qrator WAF bypass
   - `App_Cache_CitySlug` — city
   - `App_Cache_MissionAddressMode` — store (if omitted, detected automatically)
   - `PassportRefreshToken` — for future auto-refresh of the access token

Step 4. Load the cookies into the service — one of these ways:

**Auto-export from Chrome (recommended):** the script reads cookies straight
from your browser via CDP (including httpOnly ones — they cannot be copied
from JS), opens lenta.com to refresh the token, and logs the service in itself:
```bash
uv run python scripts/export_cookies.py --launch --phone 79066399816 --post
```
- `--launch` restarts your browser with a debug port (the script finds the
  running Chrome / Chrome for Testing by path and restarts it; the profile
  and cookies are kept). You need to be logged in on lenta.com in it once.
- `--post` logs the service in; if the service is not running, it suggests the command.
- Cookies are also saved to `~/Downloads/cookies-<date>.json`.
- Without `--launch` the script connects to a Chrome already running with a debug port.

**With a helper script:**
```bash
uv run python scripts/dev_login.py
# asks for phone + cookie values → POSTs to /api/auth/login
```

**Or manually via curl:**
```bash
curl -X POST 127.0.0.1:8000/api/auth/login \
     -H 'content-type: application/json' \
     -d '{"phone":"...","cookies":{"App_Cache_MPK":"<value>","PassportAccessToken":"<token>","Utk_SessionToken":"<token>","Utk_DvcGuid":"<guid>","qrator_jsid":"<token>"}}'
```

> ⚠️ All six cookies are required: without `qrator_jsid` Qrator returns **401**,
> without `Utk_DvcGuid` the gateway returns **400** (deviceid mismatch),
> without `PassportRefreshToken` an expired access token cannot be refreshed (502).
> If any are missing, the service returns `warnings` listing what is absent.

After `{"status":"manual_session_loaded","store_id":"..."}` all data routes are live.

## Data routes (require an active session)

- `GET /api/catalog/categories` — category tree of the selected store
- `GET /api/catalog/category/{nodeCode}?page=&size=` — products of a category
- `GET /api/catalog/product/{skuCode}` — product card: full category tree
  (`category_tree`), article (`article`), `slug` and `web_url`, prices
  (`regularPrice`, `discountPrice` — with discount/card), unit (`unit`:
  pc/kg), nutrition (`nutrition`: proteins/fats/carbs/kcal), `ingredients`,
  `characteristics` (all attributes), `description`
- `GET /api/search?q=&page=&size=` — search
- `GET /api/promotions/weekly` — promotions from the CMS (list, no products)
- `GET /api/promotions/crazy` — "crazy" discounts (currently empty — the `stores/crazy` upstream is unavailable)

## Cart (the same one the logged-in user sees on lenta.com)

- `GET /api/cart` — current cart
- `POST /api/cart/items` body `{"sku_code": "73015", "quantity": 2}` — add
- `PUT /api/cart/items/{skuCode}` body `{"quantity": 1}` — change quantity
  (upsert: if the item is not there — adds it)
- `DELETE /api/cart/items/{skuCode}` — remove an item
- `DELETE /api/cart` — clear the cart

Mutations go through the legacy UTK API (`POST /api/rest/cartItemAdd|cartItemModify|cartItemDelete`,
form-encoded `request={Head:{MarketingPartnerKey,SessionToken,Domain,...},Body:{...}}`).
The Head is assembled from session cookies: `App_Cache_MPK`, `Utk_SessionToken`,
`Utk_DvcGuid`, `App_Cache_CitySlug`. If UTK returns `failure/ErrorList`, the
proxy responds with `502 {"error_code":"cart_error"}` and a description.

**Unavailable products** (verified on a live cart): a stale item stays in
`items` with `Quantity: 0`, `InStockCount: 0`, `ErrorCode: "M"` and
`PriceTotal: 0`; it is not counted in `PositionsCount`/`TotalCost`. UTK
mutations then behave like this: `modify` of a dead item → 200, but the item
is **removed**; `add` of a dead SKU → 200, the item revives with qty, but on
the next read it zeroes itself out (a zeroing mechanism on lenta.com's side).
The `cart_get` MCP tool marks such lines "OUT OF STOCK".

**When unavailability becomes known** (lifecycle): the product card (`stock`)
and the mutation response (`InStockCount`) give the stock **before/right
after** adding — the `cart_add`/`cart_set_quantity` MCP tools warn immediately
from the response; an item that died **inside the cart** is zeroed out
asynchronously (seconds to minutes, `ErrorCode: "M"` on the next read). The
final availability guarantee only happens at checkout (Lenta's checkout has a
pick-an-action option for missing items). Search/catalog hide sold-out products.

Example:
```bash
curl -X POST 127.0.0.1:8000/api/cart/items \
     -H 'content-type: application/json' -d '{"sku_code":"73015","quantity":1}'
```

Examples:
```bash
curl 127.0.0.1:8000/api/catalog/categories
curl '127.0.0.1:8000/api/search?q=молоко'
curl 127.0.0.1:8000/api/promotions/weekly
```

## Auth API

- `POST /api/auth/login` body `{"phone": "...", "cookies": {...}}` → manual mode
- `POST /api/auth/login` body `{"phone": "..."}` (no cookies) → SMS flow,
  returns `nextTryAllowedAt` (non-functional without a Qrator bypass)
- `POST /api/auth/verify` body `{"code": "..."}` → completes the SMS flow
- `GET  /api/auth/status` → `{state, store_id, last_try_allowed_at}`

`state`: `idle` → `awaiting_code` → `logged_in`.

## Session expiry behavior

The access token (`PassportAccessToken`) lives ~1 hour, the refresh token
(`PassportRefreshToken`) ~6 months. On a 401 from a data request the service:
- tries to refresh the access token via `POST /api/v1/auth/passport/token/refresh`
- if the refresh fails — resets `state` → `idle` and returns
  **502** `{"error_code": "session_expired"}`
- you reload the cookies via POST /api/auth/login {phone, cookies}

A data route without login — **401** `{"error_code": "not_authenticated"}`.

The session (cookies + auth state + store) is persisted to sqlite after every
login/refresh/cookie merge, and restored on startup. A `uvicorn --reload` after
editing `app/*.py` no longer requires a re-login; on session expiry the row is
dropped and the flow above applies.

## Cache, session store and price/stock history (sqlite)

`app/store.py` keeps a single-file sqlite database (`LENTA_DB_PATH`, default
`data/lenta.db`, WAL, no extra dependencies):

- **`cache`** — raw upstream JSON per key, TTL from config:
  `LENTA_CACHE_TTL_SEARCH=600`, `LENTA_CACHE_TTL_PRODUCT=600`,
  `LENTA_CACHE_TTL_TREE=86400`, `LENTA_CACHE_TTL_PROMO=21600` (seconds).
  Cart is never cached. Cache hits skip the upstream request entirely.
- **`products`** — the current observed state per SKU (title, brand, price,
  discount, stock, rating; prices in kopecks).
- **`changes`** — a field-delta log: one row per observed field change
  (`old → new`, `NULL` old = first sighting). Written only from fresh
  (cache-miss) responses, so identical repeat searches don't spam it.
  Sparse observations (search hits without brand/rating) never clobber richer
  card data — only fields present in the observation are compared and updated.

The MCP tool `product_history(sku_code)` reads this database directly and
prints the current state, recent deltas, and the min/max price observed.

## Tests

```bash
uv sync --extra dev
uv run pytest                    # 38 tests, no network, on fixtures
uv run pytest --live -m live     # against the real lenta.com (needs a TTY for code input)
```

## Refreshing fixtures

```bash
uv run python scripts/dump_fixtures.py
```

## Stack

Python 3.12 • FastAPI • httpx (HTTP/2) • Playwright (for a future Qrator bypass) •
Pydantic v2 • uv • pytest + respx

## MVP boundaries

Not included: favorites/orders/wishlist, registration, on-the-fly store/city
switching, Redis cache, Docker/CI, token persistence across restarts,
**automatic Qrator bypass** (needs fingerprint detection — next iteration:
real Chrome via CDP or a browser extension).

## ponytail

One client class, no interface/factory — the only implementation.
No cache — add one when Lenta starts rate-limiting.
The Qrator bypass stays in the code as opt-in via `LENTA_HEADLESS=true`, but
is off by default (`bootstrap()` does not run headless — a headless pass
rotates your qrator_jsid and breaks the manual-cookie session).

## MCP for opencode

`scripts/mcp_lenta.py` — an MCP server (fastmcp, stdio) with nine tools on top
of this proxy: `search_products(query, limit)`, `get_product(sku_code)`,
`cart_get()`, `cart_add(sku_code, quantity)`, `cart_set_quantity(sku_code, quantity)`,
`cart_remove(sku_code)`, plus DB browsing (reads the observation database
directly, see the cache section above): `product_history(sku_code)`,
`db_products(query, limit)` (current state of observed products),
`db_changes(limit, field, include_first)` (a feed of recent price/stock changes
across all products; first sightings are hidden unless `include_first=true`). Registered in the global `~/.config/opencode/opencode.json`
(mcp.lenta). Requires the proxy running on `LENTA_PROXY_URL` (default
`http://127.0.0.1:8000`) and an active session; on 401 it suggests refreshing
the cookies via `scripts/export_cookies.py`.

Search output includes stock per item («ост. N» / «НЕТ В НАЛИЧИИ») — check it
before adding instead of probing the cart with add/remove. Cart mutations
return the full cart, so a follow-up `cart_get` is rarely needed.

> Cart tools mutate the same cart the user sees on lenta.com.
