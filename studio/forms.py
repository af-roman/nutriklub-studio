from __future__ import annotations

import re
from datetime import date

from studio.constants import ASSET_OPTIONS, AUDIENCES, CODE_REQUIRED, SHOPS, STATUSES, TYPE_ALIASES, TYPES
from studio.offers import extract_offer_from_form, offer_to_json, sync_legacy_fields


class FormError(Exception):
    def __init__(self, message: str):
        self.message = message
        super().__init__(message)


def parse_keys(text: str) -> list[str]:
    seen: list[str] = []
    folded = set()
    for part in re.split(r"[\n,;]+", text or ""):
        key = part.strip()
        if not key:
            continue
        token = key.casefold()
        if token in folded:
            continue
        folded.add(token)
        seen.append(key)
    return seen


def _blank(value: str | None) -> str | None:
    text = (value or "").strip()
    return text or None


def _parse_day(value: str | None, label: str) -> date | None:
    text = _blank(value)
    if text is None:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError as exc:
        raise FormError(f"{label} needs a real date.") from exc


def normalize_type(value: str) -> str:
    token = (value or "").strip()
    return TYPE_ALIASES.get(token, token)


def _as_list(value) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [value]
    return list(value)


def _optional_number(raw: str, label: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if len(text) > 40:
        raise FormError(f"{label} needs to be shorter.")
    try:
        if float(text.replace(",", ".")) < 0:
            raise FormError(f"{label} cannot be negative.")
    except ValueError as exc:
        raise FormError(f"{label} needs a number.") from exc
    return text


def parse_activity_form(form: dict) -> tuple[dict, list[str], list[dict]]:
    name = (form.get("name") or "").strip()
    if not name:
        raise FormError("Give the activity a name.")
    if len(name) > 200:
        raise FormError("The name needs to be 200 characters or fewer.")

    activity_type = normalize_type(form.get("activity_type") or "")
    if activity_type not in TYPES:
        raise FormError("Choose a type.")

    status = (form.get("status") or "").strip()
    if status not in STATUSES:
        raise FormError("Choose a status.")

    shops = (form.get("shops") or "both").strip()
    if shops not in SHOPS:
        raise FormError("Choose which shops this activity runs on.")

    start = _parse_day(form.get("start_date"), "The start date")
    end = _parse_day(form.get("end_date"), "The end date")
    if start is None or end is None:
        raise FormError("Add a start and end date.")
    if end < start:
        raise FormError("The end date is before the start date.")

    baseline_start = _parse_day(form.get("baseline_start"), "The baseline start")
    baseline_end = _parse_day(form.get("baseline_end"), "The baseline end")
    if (baseline_start is None) != (baseline_end is None):
        raise FormError("Set both baseline dates, or leave both empty.")
    if baseline_start and baseline_end and baseline_end < baseline_start:
        raise FormError("The baseline end is before the baseline start.")

    notes = (form.get("notes") or "").strip()
    if len(notes) > 5000:
        raise FormError("The notes need to be 5,000 characters or fewer.")

    product_scope = (form.get("product_scope") or "").strip()
    if len(product_scope) > 2000:
        raise FormError("The product range needs to be 2,000 characters or fewer.")

    code_required = (form.get("code_required") or "").strip()
    if code_required not in CODE_REQUIRED:
        raise FormError("Say whether a code is required, or leave it unset.")

    audience = (form.get("audience") or "all").strip()
    if audience not in AUDIENCES:
        raise FormError("Choose who can use this activity.")

    keys = parse_keys(form.get("match_keys") or "")
    if len(keys) > 30:
        raise FormError("Use 30 codes or fewer.")
    if any(len(key) > 80 for key in keys):
        raise FormError("Each code needs to be 80 characters or fewer.")

    scope_skus = _as_list(form.get("scope_skus"))
    stock_skus = _as_list(form.get("stock_sku"))
    stock_units = _as_list(form.get("stock_units"))
    stock_uplifts = _as_list(form.get("stock_uplift_line"))
    stock_asks = _as_list(form.get("stock_ask"))

    by_sku: dict[str, dict] = {}
    for sku in scope_skus:
        token = (sku or "").strip()
        if not token or len(token) > 120:
            if token and len(token) > 120:
                raise FormError("Each selected SKU needs to be 120 characters or fewer.")
            continue
        by_sku[token.casefold()] = {
            "sku": token,
            "units_per_day": "",
            "uplift": "",
            "ask_override": "",
        }

    for index, sku in enumerate(stock_skus):
        token = (sku or "").strip()
        if not token:
            continue
        key = token.casefold()
        if key not in by_sku:
            by_sku[key] = {"sku": token, "units_per_day": "", "uplift": "", "ask_override": ""}
        units = stock_units[index] if index < len(stock_units) else ""
        uplift = stock_uplifts[index] if index < len(stock_uplifts) else ""
        ask = stock_asks[index] if index < len(stock_asks) else ""
        by_sku[key]["units_per_day"] = _optional_number(units, f"Units/day for {token}")
        by_sku[key]["uplift"] = _optional_number(uplift, f"Uplift for {token}")
        by_sku[key]["ask_override"] = _optional_number(ask, f"Ask override for {token}")

    sku_lines = list(by_sku.values())
    if len(sku_lines) > 200:
        raise FormError("Select 200 SKUs or fewer.")

    objective = (form.get("objective") or "").strip()
    if len(objective) > 2000:
        raise FormError("The objective needs to be 2,000 characters or fewer.")

    asset_notes = (form.get("asset_notes") or "").strip()
    if len(asset_notes) > 5000:
        raise FormError("Asset notes need to be 5,000 characters or fewer.")

    raw_assets = _as_list(form.get("asset_option"))
    asset_keys = []
    seen_assets = set()
    for key in raw_assets:
        token = (key or "").strip()
        if not token or token not in ASSET_OPTIONS or token in seen_assets:
            continue
        seen_assets.add(token)
        asset_keys.append(token)

    offer = extract_offer_from_form(form)
    discount_kind, discount_value = sync_legacy_fields(activity_type, offer, form)
    if len(discount_value) > 120:
        discount_value = discount_value[:120]

    fields = {
        "name": name,
        "activity_type": activity_type,
        "status": status,
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "notes": notes,
        "baseline_start": baseline_start.isoformat() if baseline_start else None,
        "baseline_end": baseline_end.isoformat() if baseline_end else None,
        "shops": shops,
        "discount_kind": discount_kind,
        "discount_value": discount_value,
        "product_scope": product_scope,
        "code_required": code_required,
        "audience": audience,
        "objective": objective,
        "stock_units_per_day": "",
        "stock_uplift": "",
        "asset_notes": asset_notes,
        "offer_json": offer_to_json(offer),
        "asset_options": ",".join(asset_keys),
    }
    return fields, keys, sku_lines


def parse_schedule(start_raw: str, end_raw: str) -> tuple[str, str]:
    start = _parse_day(start_raw, "The start date")
    end = _parse_day(end_raw, "The end date")
    if start is None or end is None:
        raise FormError("Add a start and end date.")
    if end < start:
        raise FormError("The end date is before the start date.")
    return start.isoformat(), end.isoformat()
