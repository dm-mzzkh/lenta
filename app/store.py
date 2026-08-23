"""Local sqlite store: response cache, session persistence, product observations.

Layer 1 — `cache`: raw upstream JSON, TTL per endpoint (see config).
Layer 2 — `products` (current state) + `changes` (field deltas): every fresh
(cache-miss) response is observed; only fields actually present in the
observation are recorded, so a sparse search hit never clobbers a rich card.

ponytail: one connection + one module lock; per-table locks if contention
ever appears (it will not — single local user).
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
import threading
import time
from pathlib import Path
from typing import Any

from app.config import settings

_lock = threading.Lock()
_conn: sqlite3.Connection | None = None
_override: str | None = None

# columns of `products` that observations may set (SQL whitelisted)
_COLS = ("title", "brand", "price", "discount", "stock", "rating")


def _db() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        path = _override or settings.lenta_db_path
        if path != ":memory:":
            Path(path).parent.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(path, check_same_thread=False)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS cache (
                key       TEXT PRIMARY KEY,
                body      TEXT NOT NULL,
                stored_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS session (
                id         INTEGER PRIMARY KEY CHECK (id = 1),
                data       TEXT NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS products (
                sku        TEXT PRIMARY KEY,
                title      TEXT,
                brand      TEXT,
                price      INTEGER,
                discount   INTEGER,
                stock      INTEGER,
                rating     REAL,
                last_seen  REAL NOT NULL,
                updated_at REAL NOT NULL
            );
            CREATE TABLE IF NOT EXISTS changes (
                sku   TEXT NOT NULL,
                ts    REAL NOT NULL,
                field TEXT NOT NULL,
                old   TEXT,
                new   TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_changes_sku ON changes(sku, ts);
            """
        )
        _conn.commit()
    return _conn


def reset(path: str | None = None) -> None:
    """Tests: close and point the store at a fresh database (None = settings)."""
    global _conn, _override
    if _conn is not None:
        _conn.close()
    _conn = None
    _override = path


# ---------- cache ----------


def cache_get(key: str, ttl: float) -> str | None:
    row = _db().execute("SELECT body, stored_at FROM cache WHERE key=?", (key,)).fetchone()
    if row is not None and time.time() - row["stored_at"] < ttl:
        return row["body"]
    return None


def cache_put(key: str, body: str) -> None:
    with _lock:
        _db().execute(
            "INSERT OR REPLACE INTO cache(key, body, stored_at) VALUES(?,?,?)",
            (key, body, time.time()),
        )
        _db().commit()


# ---------- session ----------


def save_session(cookies: dict[str, str], meta: dict[str, Any]) -> None:
    with _lock:
        _db().execute(
            "INSERT OR REPLACE INTO session(id, data, updated_at) VALUES(1,?,?)",
            (json.dumps({"cookies": cookies, **meta}, ensure_ascii=False), time.time()),
        )
        _db().commit()


def load_session() -> dict[str, Any] | None:
    row = _db().execute("SELECT data FROM session WHERE id=1").fetchone()
    return json.loads(row["data"]) if row is not None else None


def clear_session() -> None:
    with _lock:
        _db().execute("DELETE FROM session WHERE id=1")
        _db().commit()


# ---------- observations ----------


def _int_or_none(v: Any) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def extract_item(raw: dict[str, Any]) -> tuple[str, dict[str, Any]] | None:
    """Observation fields from a raw upstream item (search/card, old+new formats).

    Prices are kopecks (int). `discount` key present with None = explicitly no
    discount; absent key = unknown/not applicable (sparse observation).
    """
    sku = raw.get("code") or raw.get("id")
    if sku is None:
        return None
    fields: dict[str, Any] = {}
    display = raw.get("display") or {}
    title = raw.get("title") or display.get("name")
    if title:
        fields["title"] = str(title)
    prices = raw.get("prices") or {}
    if prices:
        reg = _int_or_none(prices.get("priceRegular") or prices.get("costRegular"))
        disc = _int_or_none(prices.get("price") or prices.get("cost"))
        if reg is not None:
            fields["price"] = reg
        fields["discount"] = disc if disc is not None and disc != reg else None
    elif raw.get("regularPrice") is not None:  # old fixture format: rubles
        reg = round(float(raw["regularPrice"]) * 100)
        fields["price"] = reg
        if raw.get("discountPrice") is not None:
            fields["discount"] = round(float(raw["discountPrice"]) * 100)
    if raw.get("count") is not None:
        stock = _int_or_none(raw["count"])
        if stock is not None:
            fields["stock"] = stock
    elif isinstance(raw.get("stock"), str) and raw["stock"].isdigit():
        fields["stock"] = int(raw["stock"])
    brand = raw.get("brand")
    if not brand:
        for a in raw.get("attributes") or []:
            if isinstance(a, dict) and a.get("name") == "Бренд" and a.get("value"):
                brand = a["value"]
                break
    if brand:
        fields["brand"] = str(brand)
    rating = (raw.get("rating") or {}).get("rate")
    if rating is not None:
        with contextlib.suppress(TypeError, ValueError):
            fields["rating"] = float(rating)
    return str(sku), fields


def _txt(v: Any) -> str | None:
    return None if v is None else str(v)


def observe(items: list[tuple[str, dict[str, Any]] | None]) -> None:
    """Diff observations against `products`, log deltas to `changes` (one commit)."""
    clean: list[tuple[str, dict[str, Any]]] = []
    for it in items:
        if it is not None and it[1]:
            clean.append(it)
    if not clean:
        return
    with _lock:
        conn = _db()
        ts = time.time()
        deltas: list[tuple] = []
        for sku, raw_fields in clean:
            fields = {k: v for k, v in raw_fields.items() if k in _COLS}
            row = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
            if row is None:
                cols = ", ".join(fields)
                conn.execute(
                    f"INSERT INTO products(sku{',' + cols if cols else ''},"
                    "last_seen, updated_at) VALUES(?" + ",?" * (len(fields) + 2) + ")",
                    (sku, *fields.values(), ts, ts),
                )
                deltas += [(sku, ts, f, None, _txt(v)) for f, v in fields.items() if v is not None]
            else:
                deltas += [
                    (sku, ts, f, _txt(row[f]), _txt(v))
                    for f, v in fields.items()
                    if _txt(row[f]) != _txt(v)
                ]
                if fields:
                    sets = ", ".join(f"{f}=?" for f in fields)
                    changed = any(_txt(row[f]) != _txt(v) for f, v in fields.items())
                    bumped = ts if changed else row["updated_at"]
                    conn.execute(
                        f"UPDATE products SET {sets}, last_seen=?, updated_at=? WHERE sku=?",
                        (*fields.values(), ts, bumped, sku),
                    )
                else:
                    conn.execute("UPDATE products SET last_seen=? WHERE sku=?", (ts, sku))
        conn.executemany(
            "INSERT INTO changes(sku, ts, field, old, new) VALUES(?,?,?,?,?)", deltas
        )
        conn.commit()


# ---------- reads ----------


def history(sku: str, limit: int = 50) -> dict[str, Any] | None:
    """Current state + recent deltas + min/max price for one observed SKU."""
    conn = _db()
    row = conn.execute("SELECT * FROM products WHERE sku=?", (sku,)).fetchone()
    if row is None:
        return None
    d = dict(row)
    d["changes"] = [
        dict(r)
        for r in conn.execute(
            "SELECT ts, field, old, new FROM changes WHERE sku=? ORDER BY ts DESC LIMIT ?",
            (sku, limit),
        )
    ]
    prices = [
        r[0]
        for r in conn.execute(
            "SELECT DISTINCT v FROM ("
            "SELECT CAST(new AS INTEGER) v FROM changes WHERE sku=? AND field='price'"
            " UNION SELECT CAST(old AS INTEGER) v FROM changes WHERE sku=? AND field='price'"
            " UNION SELECT price v FROM products WHERE sku=?"
            ") WHERE v IS NOT NULL",
            (sku, sku, sku),
        )
    ]
    d["min_price"] = min(prices) if prices else None
    d["max_price"] = max(prices) if prices else None
    return d
