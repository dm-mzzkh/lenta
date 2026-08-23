"""MCP server for opencode: product search and cards from lenta.com via a local proxy.

Requires the proxy running: uv run uvicorn app.main:app --port 8000
(and an active session: uv run python scripts/export_cookies.py --launch --phone <number> --post).
"""

import json
import os

import httpx
from fastmcp import FastMCP

mcp = FastMCP("lenta")
base = os.environ.get("LENTA_PROXY_URL", "http://127.0.0.1:8000")
DOWN = "lenta proxy is not running. Start it: uv run uvicorn app.main:app --port 8000"
EXPIRED = (
    "lenta session has expired. Refresh: "
    "uv run python scripts/export_cookies.py --launch --phone <number> --post"
)


def _get(path: str, params: dict | None = None) -> httpx.Response:
    try:
        return httpx.get(f"{base}{path}", params=params, timeout=30)
    except httpx.ConnectError as e:
        raise RuntimeError(DOWN) from e


@mcp.tool()
async def search_products(query: str, limit: int = 10) -> str:
    """Поиск продуктов в каталоге Лента (lenta.com) по названию.

    Возвращает список: код (SKU), название, вес/объём, цены (обычная → скидочная),
    остаток («ост. N» / «НЕТ В НАЛИЧИИ»). Проверяй остаток до добавления.
    Код нужен для get_product().
    """
    limit = max(1, min(limit, 100))
    r = _get("/api/search", {"q": query, "size": limit})
    if r.status_code == 401:
        return EXPIRED
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:200]}"
    d = r.json()
    lines = [f"total: {d.get('total', '?')}"]
    for it in d.get("items", []):
        price = f"{it['regularPrice']}"
        if it.get("discountPrice") is not None:
            price += f" → {it['discountPrice']}"
        stock = it.get("stock")
        stock_note = "НЕТ В НАЛИЧИИ" if stock == "0" else f"ост. {stock}" if stock else ""
        line = f"{it['code']} | {it['title']} ({it.get('subTitle') or ''}) | {price} ₽"
        if stock_note:
            line += f" | {stock_note}"
        lines.append(line)
    return "\n".join(lines)


@mcp.tool()
async def get_product(sku_code: str) -> str:
    """Full Lenta product card by code (SKU from search_products).

    Returns JSON: article, slug, link, prices, nutrition facts, ingredients,
    characteristics, category tree, rating, stock.
    """
    r = _get(f"/api/catalog/product/{sku_code}")
    if r.status_code == 401:
        return EXPIRED
    if r.status_code == 404:
        return f"Product {sku_code} not found"
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:200]}"
    return json.dumps(r.json(), indent=2, ensure_ascii=False)


def _cart_lines(d: dict) -> list[str]:
    lines = [
        f"items: {d.get('PositionsCount', '?')} | total: {d.get('TotalCost')} ₽"
        f" (before discount {d.get('BaseTotalCost')} ₽)"
    ]
    for it in d.get("items", []):
        if it.get("InStockCount") == 0:
            lines.append(f"{it['GoodsItemId']} | {it['Name']} — OUT OF STOCK")
        else:
            lines.append(
                f"{it['GoodsItemId']} | {it['Name']} x{it['Quantity']} | "
                f"{it.get('PriceTotal')} ₽ "
                f"(each {it.get('Price')} ₽, stock {it.get('InStockCount')})"
            )
    return lines


def _stock_warning(d: dict, sku_code: str) -> str:
    """Check for the added/modified item: the mutation response already carries InStockCount."""
    # ponytail: SKU in the response is zero-padded ("073015"), the user may send "73015"
    sku = sku_code.lstrip("0") or sku_code
    for it in d.get("items", []):
        if (it["GoodsItemId"].lstrip("0") or it["GoodsItemId"]) == sku:
            if it.get("InStockCount") == 0:
                return f"WARNING: {it['Name']} — OUT OF STOCK, Lenta will zero out the item\n"
            return ""
    # empty 200 response = Lenta silently removed the item (observed for unavailable ones on modify)
    return f"WARNING: {sku_code} not found in cart — item was removed (product unavailable?)\n"


@mcp.tool()
async def cart_get() -> str:
    """Current Lenta cart: items, quantities, prices, total.

    Mutates the same cart the logged-in user sees on lenta.com.
    """
    r = _get("/api/cart")
    if r.status_code == 401:
        return EXPIRED
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:200]}"
    d = r.json()
    if not d.get("items"):
        return "Cart is empty"
    return "\n".join(_cart_lines(d))


@mcp.tool()
async def cart_add(sku_code: str, quantity: float = 1) -> str:
    """Add a product to the Lenta cart (sku_code from search_products).

    quantity is kilograms for weighted products, pieces for unit ones.
    Returns the cart after adding — a separate cart_get is not needed.
    """
    r = httpx.post(
        f"{base}/api/cart/items",
        json={"sku_code": sku_code, "quantity": quantity},
        timeout=60,
    )
    if r.status_code == 401:
        return EXPIRED
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    d = r.json()
    return _stock_warning(d, sku_code) + "\n".join(_cart_lines(d))


@mcp.tool()
async def cart_set_quantity(sku_code: str, quantity: float) -> str:
    """    Change the quantity of a product in the Lenta cart (0 is invalid — use cart_remove).

    Returns the cart after the change — a separate cart_get is not needed.
    """
    r = httpx.put(
        f"{base}/api/cart/items/{sku_code}", json={"quantity": quantity}, timeout=60
    )
    if r.status_code == 401:
        return EXPIRED
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    d = r.json()
    return _stock_warning(d, sku_code) + "\n".join(_cart_lines(d))


@mcp.tool()
async def cart_remove(sku_code: str) -> str:
    """Remove a product from the Lenta cart.

    Returns the cart after removal — a separate cart_get is not needed.
    """
    r = httpx.delete(f"{base}/api/cart/items/{sku_code}", timeout=60)
    if r.status_code == 401:
        return EXPIRED
    if r.status_code != 200:
        return f"HTTP {r.status_code}: {r.text[:300]}"
    return "\n".join(_cart_lines(r.json()))


if __name__ == "__main__":
    mcp.run()
