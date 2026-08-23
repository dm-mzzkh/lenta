from __future__ import annotations

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class _Base(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="ignore")


class Price(_Base):
    value: float | None = None
    regular: float | None = None
    discount: float | None = None
    card: float | None = None


class ProductImage(_Base):
    thumbnail: str | None = None
    medium: str | None = None
    full_size: str | None = Field(None, alias="fullSize")
    medium_lossy: str | None = Field(None, alias="mediumLossy")


class CategoryRef(_Base):
    group: dict | None = None
    category: dict | None = None
    subcategory: dict | None = Field(None, alias="subcategory")


class Product(_Base):
    code: str
    title: str
    brand: str | None = None
    sub_title: str | None = Field(None, alias="subTitle")
    description: str | None = None
    regular_price: float | None = Field(None, alias="regularPrice")
    discount_price: float | None = Field(None, alias="discountPrice")
    promo_type: str | None = Field(None, alias="promoType")
    promo_id: str | None = Field(None, alias="promoId")
    validity_start: datetime | None = Field(None, alias="validityStartDate")
    validity_end: datetime | None = Field(None, alias="validityEndDate")
    image: ProductImage | None = None
    images: list[ProductImage] = Field(default_factory=list)
    sku_weight: float | None = Field(None, alias="skuWeight")
    is_weight_product: bool = Field(False, alias="isWeightProduct")
    stock: str | None = None
    order_limit: int | None = Field(None, alias="orderLimit")
    order_steps: list[float] = Field(default_factory=list, alias="orderSteps")
    categories: CategoryRef | None = None
    average_rating: float | None = Field(None, alias="averageRating")
    comments_count: int | None = Field(None, alias="commentsCount")
    web_url: str | None = Field(None, alias="webUrl")


class Category(_Base):
    name: str
    node_code: str = Field(..., alias="nodeCode")
    children: list[Category] = Field(default_factory=list)


class SearchResult(_Base):
    items: list[Product]
    total: int = 0
    offset: int = 0
    limit: int = 24


class CategoryTreeNode(_Base):
    id: int
    name: str
    slug: str | None = None
    level: int | None = None


class Nutrition(_Base):
    proteins: float | None = None
    fats: float | None = None
    carbs: float | None = None
    calories: str | None = None  # as Lenta returns it: "340 kcal/1424 kJ"
    raw: str | None = None  # raw "Nutritional value" string from the API


class Characteristic(_Base):
    name: str
    value: str | None = None
    slug: str | None = None


class ProductDetail(Product):
    article: str | None = None  # "Art. 073015" from the product page
    slug: str | None = None  # name part of the URL: /product/{slug}-{id}/
    unit: str | None = None  # units.saleUnit: pc / kg / l
    category_tree: list[CategoryTreeNode] = Field(default_factory=list)
    nutrition: Nutrition | None = None
    ingredients: str | None = None  # "Ingredients"
    characteristics: list[Characteristic] = Field(default_factory=list)


class PromotionType(StrEnum):
    weekly = "weekly"
    crazy = "crazy"


class Promotion(_Base):
    id: str | None = None
    title: str | None = None
    discount_string: str | None = Field(None, alias="discountString")
    promo_start: datetime | None = Field(None, alias="promoStart")
    promo_end: datetime | None = Field(None, alias="promoEnd")
    is_crazy_mass_promo: bool | None = Field(None, alias="isCrazyMassPromo")
    type: PromotionType
    items: list[Product] = Field(default_factory=list)


class PromotionDetail(Promotion):
    description: str | None = None
    valid_date_range_formatted: str | None = Field(None, alias="validDateRangeFormatted")


class AuthState(StrEnum):
    idle = "idle"
    awaiting_code = "awaiting_code"
    logged_in = "logged_in"


class LoginRequest(BaseModel):
    phone: str
    # ponytail: manual cookie mode — for when Qrator blocks headless. Cookies are
    # copied from a real browser's DevTools after logging in on lenta.com.
    # Which cookies matter: App_Cache_MPK (session), qrator_jsid (WAF bypass),
    # App_Cache_CitySlug, App_Cache_MissionAddressMode (store).
    cookies: dict[str, str] | None = None


class VerifyRequest(BaseModel):
    code: str


class AuthStatus(_Base):
    state: AuthState
    store_id: str | None = None
    last_try_allowed_at: str | None = Field(None, alias="nextTryAllowedAt")


class CartItem(_Base):
    code: str = Field(..., alias="GoodsItemId")
    name: str = Field(..., alias="Name")
    quantity: float = Field(..., alias="Quantity")
    price: float | None = Field(None, alias="Price")
    price_total: float | None = Field(None, alias="PriceTotal")
    in_stock: int | None = Field(None, alias="InStockCount")
    max_sale_quantity: int | None = Field(None, alias="MaxSaleQuantity")
    image: str | None = Field(None, alias="ImageSmallUrl")
    # ponytail: ErrorCode ("M") only appears on unavailable items — the only explicit marker
    error_code: str | None = Field(None, alias="ErrorCode")


class CartSummary(_Base):
    items: list[CartItem] = Field(default_factory=list)
    positions_count: int = Field(0, alias="PositionsCount")
    total_cost: float | None = Field(None, alias="TotalCost")
    base_total_cost: float | None = Field(None, alias="BaseTotalCost")
    discount: float | None = None
    saving: float | None = None


class CartItemRequest(BaseModel):
    sku_code: str
    quantity: float = 1


class CartQuantityRequest(BaseModel):
    quantity: float


class CartError(Exception):
    """UTK cart API returned failure/ErrorList."""
