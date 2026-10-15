from __future__ import annotations

import math
import re
from datetime import date

from studio.checklist import build_checklist
from studio.constants import ASSET_OPTIONS, AUDIENCES, CODE_REQUIRED, DISCOUNT_KINDS, SHOPS, TYPES
from studio.formatting import inclusive_days
from studio.offers import offer_summary_lines, parse_offer_json


def _lines(text: str) -> list[str]:
    found = []
    for part in re.split(r"[\n,;]+", text or ""):
        item = part.strip()
        if item:
            found.append(item)
    return found


def _folded_set(text: str) -> set[str]:
    return {item.casefold() for item in _lines(text)}


def _parse_float(raw: str | None, default: float) -> float:
    text = (raw or "").strip().replace(",", ".")
    if not text:
        return default
    try:
        value = float(text)
    except ValueError:
        return default
    if value < 0:
        return default
    return value


def _parse_int(raw: str | None, default: int) -> int:
    text = (raw or "").strip()
    if not text:
        return default
    try:
        return max(0, int(float(text)))
    except ValueError:
        return default


def _activity_days(activity: dict) -> int:
    start = activity.get("start_date") or ""
    end = activity.get("end_date") or ""
    if not start or not end:
        return 0
    try:
        return inclusive_days(date.fromisoformat(start), date.fromisoformat(end))
    except ValueError:
        return 0


def _shops_overlap(a: str, b: str) -> bool:
    left = a or "both"
    right = b or "both"
    if left == "both" or right == "both":
        return True
    return left == right


def constraint_warnings(
    activity: dict,
    settings: dict,
    products: list[dict],
    others: list[dict],
) -> list[dict]:
    warnings: list[dict] = []
    blocked_skus = _folded_set(settings.get("blocked_skus") or "")
    blocked_cats = _folded_set(settings.get("blocked_categories") or "")
    min_gap = _parse_int(settings.get("min_gap_days"), 7)
    selected = list(activity.get("skus") or activity.get("scope_skus") or [])
    selected_fold = {sku.casefold() for sku in selected}
    activity_id = activity.get("id")

    for product in products:
        sku = product.get("sku") or ""
        if sku.casefold() in blocked_skus:
            warnings.append(
                {
                    "level": "block",
                    "code": "blocked_sku",
                    "title": f"Blocked SKU {sku}",
                    "detail": "This SKU is on the blocked list in Campaign rules.",
                }
            )
        cats = [part.strip() for part in re.split(r"[;|,]", product.get("categories") or "") if part.strip()]
        for cat in cats:
            if cat.casefold() in blocked_cats:
                warnings.append(
                    {
                        "level": "block",
                        "code": "blocked_category",
                        "title": f"Blocked category on {sku}",
                        "detail": f"Category “{cat}” is blocked in Campaign rules.",
                    }
                )

    if not selected and not (activity.get("product_scope") or "").strip():
        warnings.append(
            {
                "level": "warn",
                "code": "no_products",
                "title": "No products selected",
                "detail": "Pick catalog SKUs or write a product-range note before briefing stock and assets.",
            }
        )

    if not activity.get("discount_kind") and not (activity.get("discount_value") or "").strip():
        warnings.append(
            {
                "level": "warn",
                "code": "no_offer",
                "title": "Offer not specified",
                "detail": "Set discount kind and rate so briefs and the CT checklist stay consistent.",
            }
        )

    try:
        start = date.fromisoformat(activity["start_date"]) if activity.get("start_date") else None
        end = date.fromisoformat(activity["end_date"]) if activity.get("end_date") else None
    except ValueError:
        start = end = None

    if start and end and selected_fold and min_gap >= 0:
        for other in others:
            if activity_id and other.get("id") == activity_id:
                continue
            if other.get("status") == "cancelled":
                continue
            if not _shops_overlap(activity.get("shops") or "both", other.get("shops") or "both"):
                continue
            other_skus = {sku.casefold() for sku in (other.get("skus") or [])}
            shared = selected_fold & other_skus
            if not shared:
                continue
            try:
                other_start = date.fromisoformat(other["start_date"])
                other_end = date.fromisoformat(other["end_date"])
            except (KeyError, ValueError):
                continue
            # Overlap in dates
            if start <= other_end and end >= other_start:
                warnings.append(
                    {
                        "level": "block",
                        "code": "overlap_sku",
                        "title": f"Overlaps {other.get('name') or 'another activity'}",
                        "detail": (
                            f"Same storefront window and shared SKUs: {', '.join(sorted(shared)[:8])}."
                        ),
                    }
                )
                continue
            # Gap between activities (either order)
            if end < other_start:
                gap = (other_start - end).days - 1
            elif other_end < start:
                gap = (start - other_end).days - 1
            else:
                gap = 0
            if gap < min_gap:
                warnings.append(
                    {
                        "level": "warn",
                        "code": "gap",
                        "title": f"Gap below {min_gap} days vs {other.get('name') or 'another activity'}",
                        "detail": (
                            f"{gap} clear day(s) between promos sharing "
                            f"{', '.join(sorted(shared)[:6])}."
                        ),
                    }
                )

    # de-dupe by title+detail
    seen = set()
    unique = []
    for item in warnings:
        key = (item["code"], item["title"], item["detail"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return unique


def build_stock_ask(activity: dict, settings: dict, products: list[dict]) -> dict:
    days = _activity_days(activity)
    default_uplift = _parse_float(settings.get("default_stock_uplift"), 1.3)
    by_name = {item.get("sku"): item for item in products}
    sku_lines = activity.get("sku_lines") or []
    if not sku_lines and activity.get("skus"):
        sku_lines = [{"sku": sku, "units_per_day": "", "uplift": "", "ask_override": ""} for sku in activity["skus"]]

    lines = []
    total = 0
    any_ask = False
    for row in sku_lines:
        sku = row.get("sku") or ""
        product = by_name.get(sku) or {}
        units = _parse_float(row.get("units_per_day"), 0.0)
        uplift_raw = (row.get("uplift") or "").strip()
        uplift = _parse_float(uplift_raw, default_uplift) if uplift_raw else default_uplift
        if uplift <= 0:
            uplift = default_uplift
        override = (row.get("ask_override") or "").strip()
        if override:
            ask = int(math.ceil(_parse_float(override, 0.0)))
            method_bit = "manual override"
        elif units > 0 and days > 0:
            ask = int(math.ceil(units * days * uplift))
            method_bit = f"{units:g}/day × {days}d × {uplift:g}"
        else:
            ask = None
            method_bit = "set units/day"
        if ask is not None:
            total += ask
            any_ask = True
        lines.append(
            {
                "sku": sku,
                "name": product.get("name") or "",
                "categories": product.get("categories") or "",
                "units_per_day": row.get("units_per_day") or "",
                "uplift": uplift_raw or f"{default_uplift:g} (default)",
                "ask": ask,
                "method": method_bit,
            }
        )

    method = f"Per-SKU ask over {days} days (default uplift {default_uplift:g})"
    brief_lines = [
        f"Stock ask — {activity.get('name') or 'Activity'}",
        f"Window: {activity.get('start_date') or '…'} → {activity.get('end_date') or '…'} ({days} days)",
        f"Shops: {SHOPS.get(activity.get('shops') or 'both')}",
        f"Method: {method}",
        "",
    ]
    for line in lines:
        qty = str(line["ask"]) if line["ask"] is not None else "TBD"
        label = line["name"] or "—"
        brief_lines.append(
            f"- {line['sku']}: {qty} units ({label}; {line['method']})"
        )
    if not lines:
        brief_lines.append("- (no SKUs selected)")
    brief_lines.extend(
        [
            "",
            "Per-SKU assumptions on the activity. This is a planning ask, not SAP truth.",
        ]
    )
    return {
        "days": days,
        "default_uplift": default_uplift,
        "method": method,
        "lines": lines,
        "total": total if any_ask else None,
        "copy_text": "\n".join(brief_lines),
    }


def build_asset_brief(activity: dict, products: list[dict]) -> dict:
    type_label = TYPES.get(activity.get("activity_type") or "", activity.get("activity_type") or "")
    kind = DISCOUNT_KINDS.get(activity.get("discount_kind") or "", "")
    value = (activity.get("discount_value") or "").strip() or "TBD"
    codes = list(activity.get("keys") or [])
    if not codes and activity.get("match_keys"):
        codes = _lines(activity.get("match_keys") or "")
    skus = [p.get("sku") for p in products if p.get("sku")]
    names = [p.get("name") for p in products if p.get("name")]
    objective = (activity.get("objective") or "").strip() or (activity.get("notes") or "").strip() or "TBD"
    extra = (activity.get("asset_notes") or "").strip()
    offer = parse_offer_json(activity.get("offer_json") or activity.get("offer") or {})
    selected_assets = [
        key.strip()
        for key in (activity.get("asset_options") or "").split(",")
        if key.strip() in ASSET_OPTIONS
    ]
    if activity.get("asset_option_keys"):
        selected_assets = [key for key in activity["asset_option_keys"] if key in ASSET_OPTIONS]

    lines = [
        f"Asset brief — {activity.get('name') or 'Activity'}",
        "",
        f"Objective: {objective}",
        f"Markets: {SHOPS.get(activity.get('shops') or 'both')}",
        f"Dates: {activity.get('start_date') or '…'} → {activity.get('end_date') or '…'}",
        f"Mechanic: {type_label}",
        f"Offer: {kind + ' · ' if kind and kind != 'Not set' else ''}{value}",
        f"Audience: {AUDIENCES.get(activity.get('audience') or 'all')}",
        f"Code required: {CODE_REQUIRED.get(activity.get('code_required') or '', 'Not set')}",
    ]
    for summary in offer_summary_lines(
        activity.get("activity_type") or "product_discount",
        offer,
        code_required=activity.get("code_required") or "",
        audience=activity.get("audience") or "all",
    ):
        if summary.startswith("Type:") or summary.startswith("Audience:") or summary.startswith("Discount code:"):
            continue
        lines.append(summary)
    if codes:
        lines.append(f"Promo codes: {', '.join(codes)}")
    lines.append("")
    lines.append("Products:")
    if products:
        for product in products:
            bit = product.get("sku") or ""
            if product.get("name"):
                bit += f" — {product['name']}"
            lines.append(f"- {bit}")
    elif activity.get("product_scope"):
        lines.append(f"- Range note: {activity['product_scope']}")
    else:
        lines.append("- TBD")
    lines.append("")
    lines.append("Please deliver:")
    if selected_assets:
        for key in selected_assets:
            lines.append(f"- {ASSET_OPTIONS[key]}")
    else:
        lines.append("- (no formats selected yet — tick assets on the activity)")
    lines.append("")
    if extra:
        lines.append("Extra notes:")
        lines.append(extra)
    return {
        "copy_text": "\n".join(lines).strip(),
        "sku_count": len(skus),
        "named_count": len(names),
        "selected": selected_assets,
        "selected_labels": [ASSET_OPTIONS[key] for key in selected_assets],
    }


def build_legal_pack(activity: dict, settings: dict, warnings: list[dict]) -> dict:
    checks = []
    for line in _lines(settings.get("legal_checklist") or ""):
        checks.append({"text": line, "source": "rules"})
    stacking = (settings.get("stacking_notes") or "").strip()
    if stacking:
        checks.append({"text": f"Stacking / coexistence: {stacking}", "source": "rules"})
    for warning in warnings:
        if warning["level"] in {"block", "warn"}:
            checks.append(
                {
                    "text": f"Resolve before go-live: {warning['title']} — {warning['detail']}",
                    "source": "auto",
                }
            )
    copy_lines = [f"Legal / compliance — {activity.get('name') or 'Activity'}", ""]
    for index, item in enumerate(checks, start=1):
        copy_lines.append(f"{index}. [ ] {item['text']}")
    if not checks:
        copy_lines.append("1. [ ] Add legal checklist items under Settings → Campaign rules.")
    return {"checks": checks, "copy_text": "\n".join(copy_lines)}


def build_planning_packs(
    activity: dict,
    settings: dict,
    products: list[dict],
    others: list[dict] | None = None,
) -> dict:
    payload = dict(activity)
    if "keys" not in payload and payload.get("match_keys") is not None:
        payload["keys"] = _lines(payload.get("match_keys") or "")
    if "sku_lines" not in payload:
        if payload.get("scope_skus") or payload.get("skus"):
            payload["sku_lines"] = [
                {"sku": sku, "units_per_day": "", "uplift": "", "ask_override": ""}
                for sku in (payload.get("scope_skus") or payload.get("skus") or [])
            ]
        else:
            payload["sku_lines"] = []
    payload["skus"] = [line["sku"] for line in payload["sku_lines"]]
    if payload.get("offer") is None:
        payload["offer"] = parse_offer_json(payload.get("offer_json"))

    warnings = constraint_warnings(payload, settings, products, others or [])
    checklist = build_checklist(payload, settings, products)
    notes = (settings.get("notes") or "").strip()
    if notes:
        checklist["steps"].append(
            {
                "n": len(checklist["steps"]) + 1,
                "title": "Project note",
                "detail": notes,
                "copy": "",
            }
        )
    stock = build_stock_ask(payload, settings, products)
    assets = build_asset_brief(payload, products)
    legal = build_legal_pack(payload, settings, warnings)
    blocking = sum(1 for item in warnings if item["level"] == "block")
    return {
        "warnings": warnings,
        "blocking_count": blocking,
        "warning_count": len(warnings),
        "checklist": checklist,
        "stock": stock,
        "assets": assets,
        "legal": legal,
    }
