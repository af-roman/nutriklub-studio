from __future__ import annotations

import re
from datetime import date

from studio.constants import AUDIENCES, CODE_REQUIRED, DISCOUNT_KINDS, SHOPS, STATUSES, TYPE_ALIASES, TYPES


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


def parse_activity_form(form: dict) -> tuple[dict, list[str], list[str]]:
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

    discount_kind = (form.get("discount_kind") or "").strip()
    if discount_kind not in DISCOUNT_KINDS:
        raise FormError("Choose a discount kind, or leave it unset.")

    discount_value = (form.get("discount_value") or "").strip()
    if len(discount_value) > 80:
        raise FormError("The discount value needs to be 80 characters or fewer.")

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

    raw_skus = form.get("scope_skus") or []
    if isinstance(raw_skus, str):
        raw_skus = [raw_skus]
    skus: list[str] = []
    seen_skus: set[str] = set()
    for item in raw_skus:
        sku = (item or "").strip()
        if not sku or sku.casefold() in seen_skus:
            continue
        if len(sku) > 120:
            raise FormError("Each selected SKU needs to be 120 characters or fewer.")
        seen_skus.add(sku.casefold())
        skus.append(sku)
    if len(skus) > 200:
        raise FormError("Select 200 SKUs or fewer.")

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
    }
    return fields, keys, skus


def parse_schedule(start_raw: str, end_raw: str) -> tuple[str, str]:
    start = _parse_day(start_raw, "The start date")
    end = _parse_day(end_raw, "The end date")
    if start is None or end is None:
        raise FormError("Add a start and end date.")
    if end < start:
        raise FormError("The end date is before the start date.")
    return start.isoformat(), end.isoformat()
