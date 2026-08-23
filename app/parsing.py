"""Pure parsing functions extracted from LentaClient.

Stateless: take raw API dicts, return Pydantic models. No HTTP, no session.
"""

from __future__ import annotations

import re
from typing import Any

from app.schemas import (
    CartSummary,
    Category,
    Nutrition,
    Product,
    ProductDetail,
    ProductImage,
    Promotion,
    PromotionType,
    SearchResult,
)


def kopecks(value: Any) -> float | None:
    if value is None:
        return None
    return round(int(value) / 100, 2)


def images_from_api(raw: dict) -> list[ProductImage]:
    return [
        ProductImage(
            thumbnail=i.get("preview") or i.get("icon"),
            medium=i.get("medium"),
            full_size=i.get("original") or i.get("large"),
        )
        for i in raw.get("images", [])
        if isinstance(i, dict)
    ]


_NUTRITION_RE = (
    ("proteins", "белки"),
    ("fats", "жиры"),
    ("carbs", "углеводы"),
)


def nutrition_from_attrs(by_name: dict) -> Nutrition | None:
    raw_nutrition = (by_name.get("Пищевая ценность") or {}).get("value")
    calories = (by_name.get("Энергетическая ценность") or {}).get("value")
    if not raw_nutrition and not calories:
        return None
    fields: dict = {"calories": calories, "raw": raw_nutrition}
    if raw_nutrition:
        text = raw_nutrition.lower()
        for field, word in _NUTRITION_RE:
            m = re.search(rf"{word}\D*(\d+[.,]?\d*)", text)
            if m:
                fields[field] = float(m.group(1).replace(",", "."))
    return Nutrition.model_validate(fields)


def product_from_api(raw: dict) -> Product:
    if "code" in raw and "title" in raw:
        return Product.model_validate(raw)
    display = raw.get("display") or {}
    prices = raw.get("prices") or {}
    imgs = images_from_api(raw)
    return Product.model_validate(
        {
            "code": str(raw.get("id")),
            "title": display.get("name") or raw.get("name") or str(raw.get("id")),
            "subTitle": display.get("package"),
            "regularPrice": kopecks(
                prices.get("priceRegular") or prices.get("costRegular")
            ),
            "discountPrice": kopecks(prices.get("price") or prices.get("cost")),
            "images": imgs,
            "image": imgs[0] if imgs else None,
            "stock": str(raw.get("count")) if raw.get("count") is not None else None,
            "averageRating": (raw.get("rating") or {}).get("rate"),
            "commentsCount": (raw.get("rating") or {}).get("votes"),
        }
    )


def detail_from_api(raw: dict) -> ProductDetail:
    if "code" in raw and "title" in raw:
        return ProductDetail.model_validate(raw)
    attrs = raw.get("attributes") or []
    by_name = {a.get("name"): a for a in attrs if isinstance(a, dict)}
    prices = raw.get("prices") or {}
    display = raw.get("display") or {}
    regular = kopecks(prices.get("priceRegular") or prices.get("costRegular"))
    discounted = kopecks(prices.get("price") or prices.get("cost"))
    slug = raw.get("slug")
    code = str(raw.get("id") or "")
    return ProductDetail.model_validate(
        {
            "code": code,
            "title": display.get("name") or raw.get("name") or code,
            "subTitle": display.get("package"),
            "description": (by_name.get("Описание") or {}).get("value"),
            "brand": (by_name.get("Бренд") or {}).get("value"),
            "regularPrice": regular,
            "discountPrice": discounted if discounted != regular else None,
            "images": images_from_api(raw),
            "stock": str(raw.get("count")) if raw.get("count") is not None else None,
            "averageRating": (raw.get("rating") or {}).get("rate"),
            "commentsCount": (raw.get("rating") or {}).get("votes"),
            "isWeightProduct": (raw.get("features") or {}).get("isWeight"),
            "orderLimit": (raw.get("saleLimit") or {}).get("maxSaleQuantity"),
            "skuWeight": kopecks((raw.get("weight") or {}).get("gross")),
            "article": (by_name.get("Артикул") or {}).get("value") or code,
            "slug": slug,
            "unit": (raw.get("units") or {}).get("saleUnit"),
            "webUrl": f"https://lenta.com/product/{slug}-{code}/" if slug else None,
            "category_tree": [
                {
                    "id": c.get("id"),
                    "name": c.get("name"),
                    "slug": c.get("slug"),
                    "level": c.get("level"),
                }
                for c in sorted(raw.get("categories") or [], key=lambda c: c.get("level") or 0)
            ],
            "nutrition": nutrition_from_attrs(by_name),
            "ingredients": (by_name.get("Состав") or {}).get("value"),
            "characteristics": [
                {
                    "name": a.get("name"),
                    "value": a.get("value"),
                    "slug": a.get("slug") or a.get("alias"),
                }
                for a in attrs
            ],
        }
    )


def parse_category_tree(data: Any) -> list[Category]:
    if isinstance(data, dict) and isinstance(data.get("categories"), list):
        by_id: dict[int, Category] = {}
        roots: list[Category] = []
        for node in data["categories"]:
            node_id = node.get("id")
            if node_id is None:
                continue
            by_id[int(node_id)] = Category(name=node.get("name", ""), nodeCode=str(node_id))
        for node in data["categories"]:
            node_id = node.get("id")
            cat = by_id.get(int(node_id)) if node_id is not None else None
            if cat is None:
                continue
            parent_id = node.get("parentId")
            parent = by_id.get(int(parent_id)) if parent_id else None
            if parent:
                parent.children.append(cat)
            elif node.get("level") in (None, 1):
                roots.append(cat)
        return roots
    out: list[Category] = []
    for node in data if isinstance(data, list) else data.get("items", []) if data else []:
        try:
            out.append(Category.model_validate(node))
        except Exception:
            continue
    return out


def search_result_from(data: dict, offset: int, limit: int) -> SearchResult:
    skus = data.get("items")
    if skus is None:
        skus = data.get("skus", [])[offset : offset + limit]
    items = [product_from_api(s) for s in skus]
    total = int(data.get("total", data.get("skusCount", len(skus))))
    return SearchResult(items=items, total=total, offset=offset, limit=limit)


def cart_from_api(data: dict) -> CartSummary:
    carts = data.get("CartList") or []
    cart = carts[0] if carts else {}
    items = [
        {
            "GoodsItemId": g.get("GoodsItemId") or g.get("OriginalId"),
            "Name": g.get("Name"),
            "Quantity": g.get("Quantity"),
            "Price": g.get("Price"),
            "PriceTotal": g.get("PriceTotal"),
            "InStockCount": g.get("InStockCount"),
            "MaxSaleQuantity": g.get("MaxSaleQuantity"),
            "ImageSmallUrl": g.get("ImageSmallUrl"),
            "ErrorCode": g.get("ErrorCode"),
        }
        for g in cart.get("Goods") or []
    ]
    return CartSummary(
        items=items,  # type: ignore[arg-type]
        PositionsCount=cart.get("PositionsCount") or 0,
        TotalCost=cart.get("TotalCost"),
        BaseTotalCost=cart.get("BaseTotalCost"),
        discount=cart.get("DiscountValue"),
        saving=cart.get("Saving"),
    )


def promo_from_action(action: dict, promo_type: PromotionType) -> Promotion:
    return Promotion(
        id=str(action.get("pageId") or action.get("slug") or ""),
        title=action.get("name") or action.get("slugName"),
        type=promo_type,
        items=[],
    )
