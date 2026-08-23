from __future__ import annotations

import uuid
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    lenta_base_url: str = Field("https://lenta.com", alias="LENTA_BASE_URL")
    lenta_proxy_url: str = Field("http://127.0.0.1:8000", alias="LENTA_PROXY_URL")
    lenta_city_key: str = Field("spb", alias="LENTA_CITY_KEY")
    lenta_default_store_id: str = Field("", alias="LENTA_DEFAULT_STORE_ID")
    lenta_user_agent: str = Field(
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/127.0.0.0 Safari/537.36",
        alias="LENTA_USER_AGENT",
    )
    lenta_timeout: float = Field(10.0, alias="LENTA_TIMEOUT")

    lenta_device_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), alias="LENTA_DEVICE_ID"
    )
    lenta_session_id: str = Field(
        default_factory=lambda: str(uuid.uuid4()), alias="LENTA_SESSION_ID"
    )

    lenta_headless: bool = Field(False, alias="LENTA_HEADLESS")

    lenta_db_path: str = Field(str(ROOT / "data" / "lenta.db"), alias="LENTA_DB_PATH")
    lenta_cache_ttl_search: int = Field(600, alias="LENTA_CACHE_TTL_SEARCH")
    lenta_cache_ttl_product: int = Field(600, alias="LENTA_CACHE_TTL_PRODUCT")
    lenta_cache_ttl_tree: int = Field(86400, alias="LENTA_CACHE_TTL_TREE")
    lenta_cache_ttl_promo: int = Field(21600, alias="LENTA_CACHE_TTL_PROMO")



settings = Settings()