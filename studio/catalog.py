from __future__ import annotations

import csv
import json
import re

from studio.constants import CATALOG_FIELDS, SHOPS
from studio.importer import ImportProblem, decode_bytes, header_is_pii, inbox_dir, norm_header, parse_csv_text, safe_filename

PENDING_CSV = "catalog_pending.csv"
PENDING_META = "catalog_pending.json"

CATALOG_SYNONYMS = {
    "sku": ["sku", "variant sku", "product sku", "article", "article number"],
    "product_key": ["product key", "productkey", "ct product key", "commercetools product key"],
    "variant_key": ["variant key", "variantkey", "ct variant key"],
    "name": ["name", "product name", "title", "product title"],
    "categories": ["categories", "category", "category keys", "category key"],
    "shops": ["shops", "shop", "store", "stores", "market", "markets"],
}


def suggest_catalog_mapping(headers: list[str]) -> dict[str, str]:
    normalized = [(header, norm_header(header)) for header in headers]
    used: set[str] = set()
    chosen: dict[str, str] = {}

    def claim(field: str, header: str) -> None:
        chosen[field] = header
        used.add(header)

    for field, phrases in CATALOG_SYNONYMS.items():
        phrase_norms = [norm_header(phrase) for phrase in phrases]
        for header, normalized_header in normalized:
            if header in used:
                continue
            if normalized_header in phrase_norms:
                claim(field, header)
                break
    for field, phrases in CATALOG_SYNONYMS.items():
        if field in chosen:
            continue
        phrase_norms = [norm_header(phrase) for phrase in phrases if " " in phrase]
        for header, normalized_header in normalized:
            if header in used:
                continue
            if any(phrase in normalized_header for phrase in phrase_norms):
                claim(field, header)
                break
    return chosen


def normalize_shop_cell(raw: str) -> str:
    text = (raw or "").strip().casefold()
    if not text:
        return "both"
    text = text.replace(" ", "").replace("_", "")
    if text in {"both", "all", "czsk", "cz+sk", "cz/sk", "cz·sk"}:
        return "both"
    if text in {"cz", "czechia", "czech", "cs", "cs-cz"}:
        return "cz"
    if text in {"sk", "slovakia", "slovak", "sk-sk"}:
        return "sk"
    if "cz" in text and "sk" in text:
        return "both"
    return "both"


def store_catalog_upload(filename: str, raw: bytes) -> dict:
    text = decode_bytes(raw)
    headers, rows = parse_csv_text(text)
    pii_headers = [header for header in headers if header_is_pii(header)]
    kept = [header for header in headers if header not in pii_headers]
    if not kept:
        raise ImportProblem("Every column in this file looks like a customer detail. Studio has nothing to store.")
    pending = inbox_dir() / PENDING_CSV
    with pending.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=kept)
        writer.writeheader()
        for row in rows:
            writer.writerow({header: row.get(header, "") for header in kept})
    sample_row = rows[0]
    sample = {header: (sample_row.get(header) or "")[:80] for header in kept}
    meta = {
        "filename": safe_filename(filename),
        "headers": kept,
        "pii_headers": pii_headers,
        "row_count": len(rows),
        "sample": sample,
        "suggested": suggest_catalog_mapping(kept),
    }
    (inbox_dir() / PENDING_META).write_text(json.dumps(meta), encoding="utf-8")
    return meta


def load_catalog_pending() -> dict | None:
    meta_path = inbox_dir() / PENDING_META
    csv_path = inbox_dir() / PENDING_CSV
    if not meta_path.exists() or not csv_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def load_catalog_pending_rows() -> list[dict]:
    path = inbox_dir() / PENDING_CSV
    text = path.read_text(encoding="utf-8")
    _, rows = parse_csv_text(text)
    return rows


def clear_catalog_pending() -> None:
    for name in (PENDING_CSV, PENDING_META):
        path = inbox_dir() / name
        if path.exists():
            path.unlink()


def apply_catalog_mapping(rows: list[dict], mapping: dict[str, str]) -> tuple[list[dict], int]:
    built: list[dict] = []
    seen: set[tuple[str, str]] = set()
    skipped = 0
    for source in rows:

        def cell(field: str) -> str:
            header = mapping.get(field) or ""
            if not header:
                return ""
            return (source.get(header) or "").strip()

        sku = cell("sku")
        if not sku:
            skipped += 1
            continue
        shops = normalize_shop_cell(cell("shops")) if mapping.get("shops") else "both"
        if shops not in SHOPS:
            shops = "both"
        categories = cell("categories")
        categories = re.sub(r"\s*[|;]\s*", "; ", categories).strip("; ").strip()
        record = {
            "sku": sku[:120],
            "product_key": cell("product_key")[:120],
            "variant_key": cell("variant_key")[:120],
            "name": cell("name")[:200],
            "categories": categories[:500],
            "shops": shops,
        }
        key = (record["sku"].casefold(), shops)
        if key in seen:
            skipped += 1
            continue
        seen.add(key)
        built.append(record)
    return built, skipped


def catalog_fields() -> list[tuple[str, str, str, bool]]:
    return list(CATALOG_FIELDS)
