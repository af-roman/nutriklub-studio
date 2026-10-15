from __future__ import annotations

import json

from studio.constants import AUDIENCES, CODE_REQUIRED, TYPES

# Shared value modes map to Commercetools relative / absolute discount values.
VALUE_MODES = {
    "relative": "Relative (percent)",
    "absolute": "Absolute (money off)",
}

SHIPPING_MODES = {
    "free": "Free shipping",
    "absolute": "Amount off shipping",
}

GIFT_MODES = {
    "line_item": "Free gift line item (cart discount)",
    "product": "Product discount on gift SKU",
}

MULTIBUY_MODES = {
    "buy_x_get_y": "Buy X get Y free / discounted",
    "buy_x_percent": "Buy X get % off",
}


def blank_offer(activity_type: str = "product_discount") -> dict:
    base = {
        "value_mode": "relative",
        "percent": "",
        "amount_czk": "",
        "amount_eur": "",
        "sort_order": "",
        "cart_predicate_note": "",
        "shipping_mode": "free",
        "shipping_method_note": "",
        "multibuy_mode": "buy_x_get_y",
        "buy_qty": "",
        "get_qty": "",
        "get_percent": "",
        "gift_mode": "line_item",
        "gift_skus": "",
        "cart_threshold": "",
        "max_gifts": "",
        "stacking_note": "",
    }
    return base


def parse_offer_json(raw) -> dict:
    offer = blank_offer()
    if not raw:
        return offer
    if isinstance(raw, dict):
        data = raw
    else:
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            return offer
    if not isinstance(data, dict):
        return offer
    for key in offer:
        if key in data and data[key] is not None:
            offer[key] = str(data[key]).strip() if not isinstance(data[key], str) else data[key].strip()
    return offer


def offer_to_json(offer: dict) -> str:
    cleaned = blank_offer()
    cleaned.update({key: (offer.get(key) or "").strip() for key in cleaned})
    return json.dumps(cleaned, ensure_ascii=False)


def extract_offer_from_form(form: dict) -> dict:
    offer = blank_offer()
    for key in offer:
        offer[key] = (form.get(f"offer_{key}") or form.get(key) or "").strip()
    return offer


def sync_legacy_fields(activity_type: str, offer: dict, form: dict) -> tuple[str, str]:
    """Derive discount_kind + discount_value for older checklist / list views."""
    mode = offer.get("value_mode") or "relative"
    if activity_type == "shipping_discount":
        if (offer.get("shipping_mode") or "free") == "free":
            return "free", "Free shipping"
        amount = offer.get("amount_czk") or offer.get("amount_eur") or ""
        return "amount", amount or (form.get("discount_value") or "").strip()
    if activity_type == "gift":
        gifts = offer.get("gift_skus") or ""
        return "free", gifts or "Gift"
    if activity_type == "multibuy":
        if (offer.get("multibuy_mode") or "") == "buy_x_percent":
            return "percent", f"Buy {offer.get('buy_qty') or 'X'} get {offer.get('get_percent') or '?'}%"
        return "other", f"Buy {offer.get('buy_qty') or 'X'} get {offer.get('get_qty') or 'Y'}"
    if mode == "relative":
        pct = offer.get("percent") or ""
        return "percent", f"{pct}%" if pct and not pct.endswith("%") else (pct or "")
    amount = offer.get("amount_czk") or offer.get("amount_eur") or ""
    return "amount", amount


def offer_summary_lines(activity_type: str, offer: dict, *, code_required: str, audience: str) -> list[str]:
    lines = [f"Type: {TYPES.get(activity_type, activity_type)}"]
    lines.append(f"Audience: {AUDIENCES.get(audience or 'all', audience)}")
    lines.append(f"Discount code: {CODE_REQUIRED.get(code_required or '', code_required or 'Not set')}")

    if activity_type == "shipping_discount":
        lines.append(f"Shipping: {SHIPPING_MODES.get(offer.get('shipping_mode') or 'free', offer.get('shipping_mode'))}")
        if offer.get("shipping_method_note"):
            lines.append(f"Methods: {offer['shipping_method_note']}")
        if offer.get("shipping_mode") == "absolute":
            lines.append(_money_line(offer))
    elif activity_type == "multibuy":
        lines.append(f"Mechanic: {MULTIBUY_MODES.get(offer.get('multibuy_mode') or '', '')}")
        lines.append(f"Buy qty: {offer.get('buy_qty') or '—'}")
        if offer.get("multibuy_mode") == "buy_x_percent":
            lines.append(f"Get percent: {offer.get('get_percent') or '—'}%")
        else:
            lines.append(f"Get qty: {offer.get('get_qty') or '—'}")
    elif activity_type == "gift":
        lines.append(f"Gift mode: {GIFT_MODES.get(offer.get('gift_mode') or '', '')}")
        lines.append(f"Gift SKUs: {offer.get('gift_skus') or '—'}")
        if offer.get("cart_threshold"):
            lines.append(f"Cart threshold: {offer['cart_threshold']}")
        if offer.get("max_gifts"):
            lines.append(f"Max gifts: {offer['max_gifts']}")
    else:
        lines.append(f"Value: {VALUE_MODES.get(offer.get('value_mode') or 'relative', '')}")
        if (offer.get("value_mode") or "relative") == "relative":
            pct = offer.get("percent") or "—"
            lines.append(f"Percent: {pct}{'%' if pct != '—' and not str(pct).endswith('%') else ''}")
        else:
            lines.append(_money_line(offer))

    if offer.get("cart_predicate_note") and activity_type in {"cart_discount", "shipping_discount", "multibuy", "gift"}:
        lines.append(f"Cart predicate note: {offer['cart_predicate_note']}")
    if offer.get("sort_order") and activity_type in {"cart_discount", "shipping_discount", "multibuy", "gift"}:
        lines.append(f"Sort order: {offer['sort_order']}")
    if offer.get("stacking_note"):
        lines.append(f"Stacking: {offer['stacking_note']}")
    return lines


def _money_line(offer: dict) -> str:
    parts = []
    if offer.get("amount_czk"):
        parts.append(f"{offer['amount_czk']} CZK")
    if offer.get("amount_eur"):
        parts.append(f"{offer['amount_eur']} EUR")
    return "Amount: " + (", ".join(parts) if parts else "—")


def value_hint_from_offer(activity_type: str, offer: dict, currency: str) -> str:
    if activity_type == "shipping_discount":
        if (offer.get("shipping_mode") or "free") == "free":
            return "FreeShipping"
        if currency.upper() == "EUR" and offer.get("amount_eur"):
            return f"Absolute {offer['amount_eur']} EUR"
        if offer.get("amount_czk"):
            return f"Absolute {offer['amount_czk']} CZK"
        return "Absolute (set amount)"
    if activity_type == "gift":
        return f"Gift: {offer.get('gift_skus') or 'SKU TBD'}"
    if activity_type == "multibuy":
        if offer.get("multibuy_mode") == "buy_x_percent":
            return f"Buy {offer.get('buy_qty') or 'X'} → {offer.get('get_percent') or '?'}% off"
        return f"Buy {offer.get('buy_qty') or 'X'} get {offer.get('get_qty') or 'Y'}"
    if (offer.get("value_mode") or "relative") == "relative":
        pct = offer.get("percent") or ""
        return f"Relative {pct}%" if pct else "Relative (set %)"
    if currency.upper() == "EUR" and offer.get("amount_eur"):
        return f"Absolute {offer['amount_eur']} EUR"
    if offer.get("amount_czk"):
        return f"Absolute {offer['amount_czk']} CZK"
    return "Absolute (set amount)"
