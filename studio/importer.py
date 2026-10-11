from __future__ import annotations

import csv
import io
import json
import re
from datetime import date, datetime
from pathlib import Path

from studio.db import data_dir

PENDING_CSV = "pending.csv"
PENDING_META = "pending.json"

PII_PATTERNS = [
    r"\be ?mail\b",
    r"\bphone\b",
    r"\bmobile\b",
    r"\bfirst name\b",
    r"\blast name\b",
    r"\bfull name\b",
    r"\bstreet\b",
    r"\baddress\b",
    r"\bpostal\b",
    r"\bpost ?code\b",
    r"\bzip\b",
    r"\bcity\b",
    r"\bcustomer (id|email|name|phone|address)\b",
]

SYNONYMS = {
    "promo_key": ["discount code", "coupon code", "promo code", "promotion name", "coupon", "voucher", "promo"],
    "order_id": ["order number", "order no", "order id", "ordernumber", "orderid"],
    "line_id": ["line item id", "order line id", "line id"],
    "order_date": ["created at", "order date", "order created", "createdat"],
    "status": ["order status", "order state", "status", "state"],
    "sku": ["variant sku", "product sku", "sku"],
    "product_name": ["product name", "product title", "line item name", "item name"],
    "quantity": ["quantity", "qty"],
    "amount": ["line total", "total price", "line amount", "amount"],
    "discount_amount": ["discount amount", "total discount", "discounts", "discount"],
    "currency": ["currency code", "currency"],
}

BLANK_PROMOS = {"", "-", "n/a", "na", "none", "null"}


class ImportProblem(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def header_is_pii(header: str) -> bool:
    normalized = header.strip().lower().replace("-", " ").replace("_", " ")
    normalized = re.sub(r"\s+", " ", normalized)
    return any(re.search(pattern, normalized) for pattern in PII_PATTERNS)


def norm_header(header: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", header.lower()).strip()


def parse_number(raw) -> float | None:
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    text = text.replace("\u00a0", "").replace(" ", "")
    text = re.sub(r"[^0-9,.\-]", "", text)
    if text in {"", "-", ".", ",", "-.", "-,"}:
        return None
    if "," in text and "." in text:
        if text.rfind(",") > text.rfind("."):
            text = text.replace(".", "").replace(",", ".")
        else:
            text = text.replace(",", "")
    elif text.count(",") > 1 and "." not in text:
        if re.fullmatch(r"-?\d{1,3}(,\d{3})+", text):
            text = text.replace(",", "")
        else:
            return None
    elif text.count(",") == 1 and "." not in text:
        left, right = text.split(",")
        if len(right) == 3 and left.replace("-", "").isdigit():
            text = left + right
        else:
            text = left + "." + right
    try:
        return float(text)
    except ValueError:
        return None


def parse_date(raw) -> date | None:
    if raw is None:
        return None
    original = str(raw).strip()
    if not original:
        return None
    text = original.replace("Z", "")
    if "T" in text:
        text = text.split("T", 1)[0]
    elif re.match(r"\d{4}-\d{2}-\d{2} ", text):
        text = text.split(" ", 1)[0]
    for fmt in ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y", "%m/%d/%Y", "%Y/%m/%d", "%d-%m-%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(original.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def is_cancelled(status: str | None) -> bool:
    if not status:
        return False
    text = status.strip().casefold()
    return text in {"cancelled", "canceled", "cancel", "void", "voided"} or text.startswith("cancel")


def split_promos(value: str | None) -> list[str]:
    if value is None:
        return []
    found = []
    seen = set()
    for part in re.split(r"[|;,]+", str(value)):
        key = part.strip()
        if key.casefold() in BLANK_PROMOS:
            continue
        token = key.casefold()
        if token in seen:
            continue
        seen.add(token)
        found.append(key)
    return found


def suggest_mapping(headers: list[str]) -> dict[str, str]:
    normalized = [(header, norm_header(header)) for header in headers]
    used: set[str] = set()
    chosen: dict[str, str] = {}

    def claim(field: str, header: str) -> None:
        chosen[field] = header
        used.add(header)

    for field, phrases in SYNONYMS.items():
        phrase_norms = [norm_header(phrase) for phrase in phrases]
        for header, normalized_header in normalized:
            if header in used:
                continue
            if normalized_header in phrase_norms:
                claim(field, header)
                break
    for field, phrases in SYNONYMS.items():
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


def _dialect(text: str):
    sample = text[:8192]
    try:
        return csv.Sniffer().sniff(sample, delimiters=",;\t")
    except csv.Error:
        delimiter = ";" if sample.count(";") > sample.count(",") else ","

        class Fallback(csv.excel):
            pass

        Fallback.delimiter = delimiter
        return Fallback


def decode_bytes(raw: bytes) -> str:
    if raw[:2] == b"PK":
        raise ImportProblem("This looks like an Excel file. Save it as CSV and try again.")
    for encoding in ("utf-8-sig", "cp1250", "latin-1"):
        try:
            return raw.decode(encoding)
        except UnicodeDecodeError:
            continue
    return raw.decode("latin-1")


def parse_csv_text(text: str) -> tuple[list[str], list[dict]]:
    reader = csv.DictReader(io.StringIO(text), dialect=_dialect(text))
    if not reader.fieldnames:
        raise ImportProblem("The file has no column names in the first row.")
    headers = []
    for name in reader.fieldnames:
        header = (name or "").strip()
        if not header:
            raise ImportProblem("The file has a column without a name.")
        headers.append(header)
    if len(headers) != len(set(headers)):
        raise ImportProblem("Two columns share the same name. Rename them in the file and try again.")
    rows = []
    for raw_row in reader:
        if raw_row is None:
            continue
        row = {(key or "").strip(): (value or "").strip() for key, value in raw_row.items() if key}
        if any(row.values()):
            rows.append(row)
    if not rows:
        raise ImportProblem("The file has column names and no orders.")
    return headers, rows


def inbox_dir() -> Path:
    path = data_dir() / "inbox"
    path.mkdir(parents=True, exist_ok=True)
    return path


def safe_filename(name: str | None) -> str:
    base = Path(name or "orders.csv").name
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "_", base).strip("._")
    return (cleaned or "orders.csv")[:120]


def store_upload(filename: str, raw: bytes) -> dict:
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
        "suggested": suggest_mapping(kept),
    }
    (inbox_dir() / PENDING_META).write_text(json.dumps(meta), encoding="utf-8")
    return meta


def load_pending() -> dict | None:
    meta_path = inbox_dir() / PENDING_META
    csv_path = inbox_dir() / PENDING_CSV
    if not meta_path.exists() or not csv_path.exists():
        return None
    return json.loads(meta_path.read_text(encoding="utf-8"))


def load_pending_rows() -> list[dict]:
    path = inbox_dir() / PENDING_CSV
    text = path.read_text(encoding="utf-8")
    _, rows = parse_csv_text(text)
    return rows


def clear_pending() -> None:
    for name in (PENDING_CSV, PENDING_META):
        path = inbox_dir() / name
        if path.exists():
            path.unlink()


def apply_mapping(rows: list[dict], mapping: dict[str, str]) -> tuple[list[dict], int]:
    merged: dict[tuple[str, str], dict] = {}
    skipped = 0
    for source in rows:
        def cell(field: str) -> str:
            header = mapping.get(field) or ""
            if not header:
                return ""
            return (source.get(header) or "").strip()

        order_id = cell("order_id")
        parsed_day = parse_date(cell("order_date"))
        if not order_id or parsed_day is None:
            skipped += 1
            continue
        line_id = cell("line_id")
        status = cell("status") or None
        record = {
            "order_id": order_id,
            "line_id": line_id,
            "order_date": parsed_day.isoformat(),
            "status": status,
            "cancelled": is_cancelled(status),
            "sku": cell("sku") or None,
            "product_name": cell("product_name") or None,
            "quantity": parse_number(cell("quantity")) if mapping.get("quantity") else None,
            "amount": parse_number(cell("amount")) if mapping.get("amount") else None,
            "discount_amount": parse_number(cell("discount_amount")) if mapping.get("discount_amount") else None,
            "currency": (cell("currency") or "").upper() or None,
            "promos": split_promos(cell("promo_key")) if mapping.get("promo_key") else [],
        }
        key = (order_id, line_id)
        if key in merged:
            promos = merged[key]["promos"] + record["promos"]
            merged[key].update(record)
            merged[key]["promos"] = split_promos("|".join(promos))
        else:
            merged[key] = record
    built = list(merged.values())
    return built, skipped
