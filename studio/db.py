from __future__ import annotations

import os
import sqlite3
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

SCHEMA = """
CREATE TABLE IF NOT EXISTS activities (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    activity_type TEXT NOT NULL,
    status TEXT NOT NULL,
    start_date TEXT NOT NULL,
    end_date TEXT NOT NULL,
    notes TEXT NOT NULL DEFAULT '',
    baseline_start TEXT,
    baseline_end TEXT,
    shops TEXT NOT NULL DEFAULT 'both',
    discount_kind TEXT NOT NULL DEFAULT '',
    discount_value TEXT NOT NULL DEFAULT '',
    product_scope TEXT NOT NULL DEFAULT '',
    code_required TEXT NOT NULL DEFAULT '',
    audience TEXT NOT NULL DEFAULT 'all',
    objective TEXT NOT NULL DEFAULT '',
    stock_units_per_day TEXT NOT NULL DEFAULT '',
    stock_uplift TEXT NOT NULL DEFAULT '',
    asset_notes TEXT NOT NULL DEFAULT '',
    offer_json TEXT NOT NULL DEFAULT '{}',
    asset_options TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_keys (
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    promo_key TEXT NOT NULL,
    PRIMARY KEY (activity_id, promo_key)
);

CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL,
    order_count INTEGER NOT NULL,
    line_count INTEGER NOT NULL,
    grain TEXT NOT NULL,
    has_quantity INTEGER NOT NULL,
    has_amount INTEGER NOT NULL,
    has_discount INTEGER NOT NULL,
    skipped_rows INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS mappings (
    field TEXT PRIMARY KEY,
    csv_header TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS order_lines (
    order_id TEXT NOT NULL,
    line_id TEXT NOT NULL DEFAULT '',
    order_date TEXT NOT NULL,
    status TEXT,
    cancelled INTEGER NOT NULL DEFAULT 0,
    sku TEXT,
    product_name TEXT,
    quantity REAL,
    amount REAL,
    discount_amount REAL,
    currency TEXT,
    PRIMARY KEY (order_id, line_id)
);

CREATE TABLE IF NOT EXISTS order_promos (
    order_id TEXT NOT NULL,
    line_id TEXT NOT NULL,
    promo_key TEXT NOT NULL,
    promo_key_norm TEXT NOT NULL,
    PRIMARY KEY (order_id, line_id, promo_key_norm)
);

CREATE INDEX IF NOT EXISTS idx_lines_date ON order_lines(order_date);

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS catalog_products (
    id INTEGER PRIMARY KEY,
    sku TEXT NOT NULL,
    product_key TEXT NOT NULL DEFAULT '',
    variant_key TEXT NOT NULL DEFAULT '',
    name TEXT NOT NULL DEFAULT '',
    categories TEXT NOT NULL DEFAULT '',
    shops TEXT NOT NULL DEFAULT 'both'
);

CREATE INDEX IF NOT EXISTS idx_catalog_sku ON catalog_products(sku);
CREATE INDEX IF NOT EXISTS idx_catalog_name ON catalog_products(name);

CREATE TABLE IF NOT EXISTS catalog_mappings (
    field TEXT PRIMARY KEY,
    csv_header TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS activity_skus (
    activity_id INTEGER NOT NULL REFERENCES activities(id) ON DELETE CASCADE,
    sku TEXT NOT NULL,
    units_per_day TEXT NOT NULL DEFAULT '',
    uplift TEXT NOT NULL DEFAULT '',
    ask_override TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (activity_id, sku)
);

CREATE TABLE IF NOT EXISTS catalog_imports (
    id INTEGER PRIMARY KEY,
    filename TEXT NOT NULL,
    imported_at TEXT NOT NULL,
    row_count INTEGER NOT NULL
);
"""


def data_dir() -> Path:
    path = Path(os.environ.get("STUDIO_DATA", ROOT / "data"))
    path.mkdir(parents=True, exist_ok=True)
    return path


def db_path() -> Path:
    return Path(os.environ.get("STUDIO_DB", data_dir() / "studio.db"))


def now_stamp() -> str:
    return datetime.now().astimezone().replace(microsecond=0).isoformat()


def connect() -> sqlite3.Connection:
    path = db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    columns = {row["name"] for row in conn.execute("PRAGMA table_info(activities)")}
    if columns:
        additions = [
            ("shops", "TEXT NOT NULL DEFAULT 'both'"),
            ("discount_kind", "TEXT NOT NULL DEFAULT ''"),
            ("discount_value", "TEXT NOT NULL DEFAULT ''"),
            ("product_scope", "TEXT NOT NULL DEFAULT ''"),
            ("code_required", "TEXT NOT NULL DEFAULT ''"),
            ("audience", "TEXT NOT NULL DEFAULT 'all'"),
            ("objective", "TEXT NOT NULL DEFAULT ''"),
            ("stock_units_per_day", "TEXT NOT NULL DEFAULT ''"),
            ("stock_uplift", "TEXT NOT NULL DEFAULT ''"),
            ("asset_notes", "TEXT NOT NULL DEFAULT ''"),
            ("offer_json", "TEXT NOT NULL DEFAULT '{}'"),
            ("asset_options", "TEXT NOT NULL DEFAULT ''"),
        ]
        for name, definition in additions:
            if name not in columns:
                conn.execute(f"ALTER TABLE activities ADD COLUMN {name} {definition}")
        sku_columns = {row["name"] for row in conn.execute("PRAGMA table_info(activity_skus)")}
        for name, definition in [
            ("units_per_day", "TEXT NOT NULL DEFAULT ''"),
            ("uplift", "TEXT NOT NULL DEFAULT ''"),
            ("ask_override", "TEXT NOT NULL DEFAULT ''"),
        ]:
            if name not in sku_columns:
                conn.execute(f"ALTER TABLE activity_skus ADD COLUMN {name} {definition}")
        conn.execute(
            """
            UPDATE activities SET activity_type = CASE activity_type
                WHEN 'discount_code' THEN 'product_discount'
                WHEN 'offer' THEN 'product_discount'
                WHEN 'bundle' THEN 'multibuy'
                WHEN 'campaign' THEN 'product_discount'
                WHEN 'other' THEN 'product_discount'
                ELSE activity_type
            END
            WHERE activity_type IN ('discount_code', 'offer', 'bundle', 'campaign', 'other')
            """
        )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_promos_order ON order_promos(order_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_promos_norm ON order_promos(promo_key_norm)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lines_sku_date ON order_lines(sku, order_date)")
    return conn


@contextmanager
def session():
    conn = connect()
    try:
        yield conn
    except Exception:
        conn.rollback()
        raise
    else:
        conn.commit()
    finally:
        conn.close()


def _hydrate(conn: sqlite3.Connection, rows) -> list[dict]:
    items = [dict(row) for row in rows]
    if not items:
        return []
    ids = [item["id"] for item in items]
    placeholders = ",".join("?" for _ in ids)
    keys: dict[int, list[str]] = {}
    sku_lines: dict[int, list[dict]] = {}
    query = f"SELECT activity_id, promo_key FROM activity_keys WHERE activity_id IN ({placeholders}) ORDER BY promo_key"
    for row in conn.execute(query, ids):
        keys.setdefault(row["activity_id"], []).append(row["promo_key"])
    sku_query = (
        f"SELECT activity_id, sku, units_per_day, uplift, ask_override "
        f"FROM activity_skus WHERE activity_id IN ({placeholders}) ORDER BY sku"
    )
    for row in conn.execute(sku_query, ids):
        sku_lines.setdefault(row["activity_id"], []).append(
            {
                "sku": row["sku"],
                "units_per_day": row["units_per_day"] or "",
                "uplift": row["uplift"] or "",
                "ask_override": row["ask_override"] or "",
            }
        )
    for item in items:
        lines = sku_lines.get(item["id"], [])
        item["keys"] = keys.get(item["id"], [])
        item["sku_lines"] = lines
        item["skus"] = [line["sku"] for line in lines]
        item["offer_json"] = item.get("offer_json") or "{}"
        item["asset_options"] = item.get("asset_options") or ""
    return items


def list_activities(conn: sqlite3.Connection, year: int | None = None) -> list[dict]:
    if year is None:
        rows = conn.execute("SELECT * FROM activities ORDER BY start_date, id")
    else:
        rows = conn.execute(
            """
            SELECT * FROM activities
            WHERE start_date <= ? AND end_date >= ?
            ORDER BY start_date, id
            """,
            (f"{year}-12-31", f"{year}-01-01"),
        )
    return _hydrate(conn, rows)


def get_activity(conn: sqlite3.Connection, activity_id: int) -> dict | None:
    row = conn.execute("SELECT * FROM activities WHERE id = ?", (activity_id,)).fetchone()
    if row is None:
        return None
    return _hydrate(conn, [row])[0]


def get_latest_activity(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM activities ORDER BY updated_at DESC, id DESC LIMIT 1").fetchone()
    if row is None:
        return None
    return _hydrate(conn, [row])[0]


def _replace_keys(conn: sqlite3.Connection, activity_id: int, keys: list[str]) -> None:
    conn.execute("DELETE FROM activity_keys WHERE activity_id = ?", (activity_id,))
    conn.executemany(
        "INSERT INTO activity_keys (activity_id, promo_key) VALUES (?, ?)",
        [(activity_id, key) for key in keys],
    )


def _normalize_sku_lines(skus) -> list[dict]:
    lines: list[dict] = []
    seen: set[str] = set()
    for item in skus or []:
        if isinstance(item, str):
            sku = item.strip()
            line = {"sku": sku, "units_per_day": "", "uplift": "", "ask_override": ""}
        else:
            sku = (item.get("sku") or "").strip()
            line = {
                "sku": sku,
                "units_per_day": (item.get("units_per_day") or "").strip(),
                "uplift": (item.get("uplift") or "").strip(),
                "ask_override": (item.get("ask_override") or "").strip(),
            }
        if not sku or sku.casefold() in seen:
            continue
        seen.add(sku.casefold())
        lines.append(line)
    return lines


def _replace_skus(conn: sqlite3.Connection, activity_id: int, skus) -> None:
    lines = _normalize_sku_lines(skus)
    conn.execute("DELETE FROM activity_skus WHERE activity_id = ?", (activity_id,))
    conn.executemany(
        """
        INSERT INTO activity_skus (activity_id, sku, units_per_day, uplift, ask_override)
        VALUES (?, ?, ?, ?, ?)
        """,
        [
            (activity_id, line["sku"], line["units_per_day"], line["uplift"], line["ask_override"])
            for line in lines
        ],
    )


def create_activity(conn: sqlite3.Connection, fields: dict, keys: list[str], skus=None) -> int:
    stamp = now_stamp()
    cursor = conn.execute(
        """
        INSERT INTO activities (
            name, activity_type, status, start_date, end_date, notes,
            baseline_start, baseline_end, shops,
            discount_kind, discount_value, product_scope, code_required, audience,
            objective, stock_units_per_day, stock_uplift, asset_notes,
            offer_json, asset_options,
            created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            fields["name"],
            fields["activity_type"],
            fields["status"],
            fields["start_date"],
            fields["end_date"],
            fields["notes"],
            fields["baseline_start"],
            fields["baseline_end"],
            fields.get("shops") or "both",
            fields.get("discount_kind") or "",
            fields.get("discount_value") or "",
            fields.get("product_scope") or "",
            fields.get("code_required") or "",
            fields.get("audience") or "all",
            fields.get("objective") or "",
            fields.get("stock_units_per_day") or "",
            fields.get("stock_uplift") or "",
            fields.get("asset_notes") or "",
            fields.get("offer_json") or "{}",
            fields.get("asset_options") or "",
            stamp,
            stamp,
        ),
    )
    activity_id = int(cursor.lastrowid)
    _replace_keys(conn, activity_id, keys)
    _replace_skus(conn, activity_id, skus or [])
    return activity_id


def update_activity(
    conn: sqlite3.Connection,
    activity_id: int,
    fields: dict,
    keys: list[str],
    skus: list[str] | None = None,
) -> None:
    conn.execute(
        """
        UPDATE activities SET
            name = ?, activity_type = ?, status = ?, start_date = ?, end_date = ?,
            notes = ?, baseline_start = ?, baseline_end = ?, shops = ?,
            discount_kind = ?, discount_value = ?, product_scope = ?,
            code_required = ?, audience = ?,
            objective = ?, stock_units_per_day = ?, stock_uplift = ?, asset_notes = ?,
            offer_json = ?, asset_options = ?,
            updated_at = ?
        WHERE id = ?
        """,
        (
            fields["name"],
            fields["activity_type"],
            fields["status"],
            fields["start_date"],
            fields["end_date"],
            fields["notes"],
            fields["baseline_start"],
            fields["baseline_end"],
            fields.get("shops") or "both",
            fields.get("discount_kind") or "",
            fields.get("discount_value") or "",
            fields.get("product_scope") or "",
            fields.get("code_required") or "",
            fields.get("audience") or "all",
            fields.get("objective") or "",
            fields.get("stock_units_per_day") or "",
            fields.get("stock_uplift") or "",
            fields.get("asset_notes") or "",
            fields.get("offer_json") or "{}",
            fields.get("asset_options") or "",
            now_stamp(),
            activity_id,
        ),
    )
    _replace_keys(conn, activity_id, keys)
    if skus is not None:
        _replace_skus(conn, activity_id, skus)


def update_activity_dates(conn: sqlite3.Connection, activity_id: int, start_date: str, end_date: str) -> dict | None:
    activity = get_activity(conn, activity_id)
    if activity is None:
        return None
    conn.execute(
        """
        UPDATE activities SET start_date = ?, end_date = ?, updated_at = ?
        WHERE id = ?
        """,
        (start_date, end_date, now_stamp(), activity_id),
    )
    activity["start_date"] = start_date
    activity["end_date"] = end_date
    return activity


def duplicate_activity(conn: sqlite3.Connection, activity_id: int) -> int | None:
    source = get_activity(conn, activity_id)
    if source is None:
        return None
    name = f"Copy of {source['name']}"[:200]
    fields = {
        "name": name,
        "activity_type": source["activity_type"],
        "status": "draft",
        "start_date": source["start_date"],
        "end_date": source["end_date"],
        "notes": source["notes"],
        "baseline_start": source["baseline_start"],
        "baseline_end": source["baseline_end"],
        "shops": source.get("shops") or "both",
        "discount_kind": source.get("discount_kind") or "",
        "discount_value": source.get("discount_value") or "",
        "product_scope": source.get("product_scope") or "",
        "code_required": source.get("code_required") or "",
        "audience": source.get("audience") or "all",
        "objective": source.get("objective") or "",
        "stock_units_per_day": source.get("stock_units_per_day") or "",
        "stock_uplift": source.get("stock_uplift") or "",
        "asset_notes": source.get("asset_notes") or "",
        "offer_json": source.get("offer_json") or "{}",
        "asset_options": source.get("asset_options") or "",
    }
    return create_activity(
        conn,
        fields,
        list(source["keys"]),
        list(source.get("sku_lines") or source.get("skus") or []),
    )


def delete_activity(conn: sqlite3.Connection, activity_id: int) -> None:
    conn.execute("DELETE FROM activities WHERE id = ?", (activity_id,))


def get_settings(conn: sqlite3.Connection) -> dict[str, str]:
    from studio.constants import DEFAULT_SETTINGS

    stored = {row["key"]: row["value"] for row in conn.execute("SELECT key, value FROM settings")}
    merged = dict(DEFAULT_SETTINGS)
    merged.update(stored)
    return merged


def save_settings(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    from studio.constants import DEFAULT_SETTINGS

    rows = []
    for key in DEFAULT_SETTINGS:
        if key in values:
            rows.append((key, values[key]))
    conn.executemany(
        "INSERT INTO settings (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        rows,
    )


def list_catalog(conn: sqlite3.Connection, shop: str | None = None, q: str = "") -> list[dict]:
    rows = conn.execute(
        "SELECT * FROM catalog_products ORDER BY name COLLATE NOCASE, sku COLLATE NOCASE, id"
    ).fetchall()
    items = [dict(row) for row in rows]
    if shop and shop in {"cz", "sk"}:
        items = [item for item in items if item["shops"] in {"both", shop}]
    needle = (q or "").strip().casefold()
    if needle:
        items = [
            item
            for item in items
            if needle in (item["sku"] or "").casefold()
            or needle in (item["name"] or "").casefold()
            or needle in (item["product_key"] or "").casefold()
            or needle in (item["categories"] or "").casefold()
        ]
    return items


def catalog_count(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT COUNT(*) AS n FROM catalog_products").fetchone()
    return int(row["n"]) if row else 0


def latest_catalog_import(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM catalog_imports ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None


def replace_catalog(conn: sqlite3.Connection, rows: list[dict], meta: dict) -> None:
    conn.execute("DELETE FROM catalog_products")
    conn.executemany(
        """
        INSERT INTO catalog_products (sku, product_key, variant_key, name, categories, shops)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        [
            (
                row["sku"],
                row.get("product_key") or "",
                row.get("variant_key") or "",
                row.get("name") or "",
                row.get("categories") or "",
                row.get("shops") or "both",
            )
            for row in rows
        ],
    )
    conn.execute(
        "INSERT INTO catalog_imports (filename, imported_at, row_count) VALUES (?, ?, ?)",
        (meta["filename"], now_stamp(), len(rows)),
    )


def save_catalog_mapping(conn: sqlite3.Connection, mapping: dict[str, str]) -> None:
    conn.execute("DELETE FROM catalog_mappings")
    rows = [(field, header) for field, header in mapping.items() if header]
    conn.executemany("INSERT INTO catalog_mappings (field, csv_header) VALUES (?, ?)", rows)


def get_catalog_mapping(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["field"]: row["csv_header"]
        for row in conn.execute("SELECT field, csv_header FROM catalog_mappings")
    }


def save_mapping(conn: sqlite3.Connection, mapping: dict[str, str]) -> None:
    conn.execute("DELETE FROM mappings")
    rows = [(field, header) for field, header in mapping.items() if header]
    conn.executemany("INSERT INTO mappings (field, csv_header) VALUES (?, ?)", rows)


def get_mapping(conn: sqlite3.Connection) -> dict[str, str]:
    return {row["field"]: row["csv_header"] for row in conn.execute("SELECT field, csv_header FROM mappings")}


def replace_orders(conn: sqlite3.Connection, rows: list[dict], meta: dict) -> None:
    conn.execute("DELETE FROM order_promos")
    conn.execute("DELETE FROM order_lines")
    for row in rows:
        conn.execute(
            """
            INSERT INTO order_lines (
                order_id, line_id, order_date, status, cancelled, sku, product_name,
                quantity, amount, discount_amount, currency
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["order_id"],
                row["line_id"],
                row["order_date"],
                row["status"],
                1 if row["cancelled"] else 0,
                row["sku"],
                row["product_name"],
                row["quantity"],
                row["amount"],
                row["discount_amount"],
                row["currency"],
            ),
        )
        seen = set()
        for promo in row["promos"]:
            norm = promo.casefold()
            if norm in seen:
                continue
            seen.add(norm)
            conn.execute(
                """
                INSERT INTO order_promos (order_id, line_id, promo_key, promo_key_norm)
                VALUES (?, ?, ?, ?)
                """,
                (row["order_id"], row["line_id"], promo, norm),
            )
    order_count = len({row["order_id"] for row in rows})
    conn.execute(
        """
        INSERT INTO imports (
            filename, imported_at, row_count, order_count, line_count, grain,
            has_quantity, has_amount, has_discount, skipped_rows
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            meta["filename"],
            now_stamp(),
            meta["row_count"],
            order_count,
            len(rows),
            meta["grain"],
            1 if meta["has_quantity"] else 0,
            1 if meta["has_amount"] else 0,
            1 if meta["has_discount"] else 0,
            meta["skipped_rows"],
        ),
    )


def latest_import(conn: sqlite3.Connection) -> dict | None:
    row = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 1").fetchone()
    return dict(row) if row else None
