from __future__ import annotations

import re
from datetime import date

from studio.constants import AUDIENCES, CODE_REQUIRED, DISCOUNT_KINDS, SHOP_MODELS, SHOPS, TYPES
from studio.offers import offer_summary_lines, parse_offer_json, value_hint_from_offer


def _slug(text: str) -> str:
    cleaned = re.sub(r"[^a-z0-9]+", "-", (text or "").strip().casefold())
    return cleaned.strip("-")[:48] or "activity"


def _fill_pattern(pattern: str, *, slug: str, code: str, start: str) -> str:
    yyyy_mm = start[:7] if start else date.today().strftime("%Y-%m")
    return (
        (pattern or "")
        .replace("{slug}", slug)
        .replace("{code}", code or slug)
        .replace("{yyyy-mm}", yyyy_mm)
        .replace("{yyyy_mm}", yyyy_mm.replace("-", "_"))
    )


def _shop_targets(activity: dict, settings: dict) -> list[dict]:
    shops = activity.get("shops") or "both"
    model = settings.get("shop_model") or "stores"
    model_label = SHOP_MODELS.get(model, SHOP_MODELS["stores"])
    targets = []
    if shops in {"both", "cz"}:
        targets.append(
            {
                "shop": "cz",
                "label": "Czechia",
                "key": (settings.get("cz_key") or "").strip() or "(set CZ key in Settings)",
                "locale": settings.get("locale_cz") or "cs-CZ",
                "currency": settings.get("currency_cz") or "CZK",
            }
        )
    if shops in {"both", "sk"}:
        targets.append(
            {
                "shop": "sk",
                "label": "Slovakia",
                "key": (settings.get("sk_key") or "").strip() or "(set SK key in Settings)",
                "locale": settings.get("locale_sk") or "sk-SK",
                "currency": settings.get("currency_sk") or "EUR",
            }
        )
    for target in targets:
        target["model"] = model
        target["model_label"] = model_label
        if model == "stores":
            target["where"] = f"Store key {target['key']}"
        else:
            target["where"] = f"Project key {target['key']}"
    return targets


def _predicate(settings: dict, products: list[dict]) -> str:
    style = settings.get("predicate_style") or "sku"
    if not products:
        return "(select products on the activity, or write a category predicate)"
    if style == "product_key":
        keys = [item.get("product_key") or item["sku"] for item in products]
        keys = [key for key in keys if key]
        if len(keys) == 1:
            return f'product.key = "{keys[0]}"'
        joined = ", ".join(f'"{key}"' for key in keys)
        return f"product.key in ({joined})"
    skus = [item["sku"] for item in products if item.get("sku")]
    if len(skus) == 1:
        return f'sku = "{skus[0]}"'
    joined = ", ".join(f'"{sku}"' for sku in skus)
    return f"sku in ({joined})"


def _value_hint(activity: dict, currency: str) -> str:
    offer = parse_offer_json(activity.get("offer_json") or activity.get("offer") or {})
    hinted = value_hint_from_offer(activity.get("activity_type") or "product_discount", offer, currency)
    if hinted and "set" not in hinted.lower():
        return hinted
    kind = activity.get("discount_kind") or ""
    value = (activity.get("discount_value") or "").strip()
    if not value:
        return DISCOUNT_KINDS.get(kind, "Not set")
    if kind == "percent":
        return f"Relative ({value})"
    if kind == "amount":
        return f"Absolute {value} ({currency})"
    if kind == "free":
        return f"Free / gift · {value}"
    return value


def build_checklist(activity: dict, settings: dict, products: list[dict] | None = None) -> dict:
    products = products or []
    activity_type = activity.get("activity_type") or "product_discount"
    type_label = TYPES.get(activity_type, activity_type)
    slug = _slug(activity.get("name") or "activity")
    start = activity.get("start_date") or ""
    end = activity.get("end_date") or ""
    codes = list(activity.get("keys") or [])
    primary_code = codes[0] if codes else ""
    code_required = activity.get("code_required") or ""
    audience = activity.get("audience") or "all"
    offer = parse_offer_json(activity.get("offer_json") or activity.get("offer") or {})
    targets = _shop_targets(activity, settings)
    predicate = _predicate(settings, products)
    sort_order = (
        (offer.get("sort_order") or "").strip()
        or (settings.get("default_sort_order") or "0.5").strip()
        or "0.5"
    )
    group_key = (settings.get("registered_customer_group_key") or "").strip()

    cart_key = _fill_pattern(settings.get("key_pattern_cart") or "", slug=slug, code=primary_code, start=start)
    product_key = _fill_pattern(settings.get("key_pattern_product") or "", slug=slug, code=primary_code, start=start)
    code_key_pattern = settings.get("key_pattern_code") or "code-{code}"

    needs_product_discount = activity_type in {"product_discount", "multibuy", "gift"}
    needs_cart_discount = activity_type in {"cart_discount", "shipping_discount", "multibuy", "gift"} or code_required == "yes"
    needs_code = code_required == "yes" or bool(codes)
    is_shipping = activity_type == "shipping_discount"

    steps: list[dict] = []
    n = 1

    def add(title: str, detail: str, copy: str = "") -> None:
        nonlocal n
        steps.append({"n": n, "title": title, "detail": detail, "copy": copy})
        n += 1

    add(
        "Confirm shops",
        f"Activity shops: {SHOPS.get(activity.get('shops') or 'both')}. "
        f"Project layout: {SHOP_MODELS.get(settings.get('shop_model') or 'stores')}. "
        + (
            "Create or update the discount in each target below."
            if len(targets) > 1
            else "Create or update the discount for the target below."
        ),
    )
    add(
        "Offer summary",
        " · ".join(
            offer_summary_lines(
                activity_type,
                offer,
                code_required=code_required,
                audience=audience,
            )
        ),
    )

    for target in targets:
        currency = target["currency"]
        value_hint = _value_hint(activity, currency)
        store_key = (settings.get(f"{target['shop']}_key") or "").strip()
        if settings.get("shop_model") == "stores":
            if store_key:
                scope = f"Limit the discount to Store key {store_key}."
            else:
                scope = f"Set the {target['label']} store key in Settings, then limit the discount to that Store."
        else:
            if store_key:
                scope = f"Create this in project {store_key}."
            else:
                scope = f"Set the {target['label']} project key in Settings, then create the discount there."

        if needs_product_discount and not is_shipping:
            add(
                f"{target['label']}: Product discount",
                f"Merchant Center → Discounts → Product discounts → Add. "
                f"Name: {activity.get('name') or 'Activity'}. "
                f"Key suggestion: {product_key}. "
                f"Valid from {start or '…'} to {end or '…'}. "
                f"Value: {value_hint}. "
                f"Predicate: {predicate}. "
                f"{scope} Locale for labels: {target['locale']}.",
                predicate,
            )

        if needs_cart_discount or is_shipping:
            cart_kind = "Shipping" if is_shipping else "Cart"
            cart_extra = ""
            if audience == "registered":
                if group_key:
                    cart_extra = f" Customer predicate: customer.customerGroup.key = \"{group_key}\"."
                else:
                    cart_extra = " Audience is registered users — set the customer group key in Settings, then add a customer-group predicate."
            if needs_code:
                cart_extra += " Requires a discount code (create the cart discount first, then the code)."
            add(
                f"{target['label']}: {cart_kind} discount",
                f"Merchant Center → Discounts → Cart discounts → Add. "
                f"Name: {activity.get('name') or 'Activity'}. "
                f"Key suggestion: {cart_key}. "
                f"Valid from {start or '…'} to {end or '…'}. "
                f"Value: {value_hint}. "
                f"Cart/product predicate: {predicate}. "
                f"Sort order: {sort_order}. "
                f"{scope} Currency: {currency}.{cart_extra}",
                predicate,
            )

        if needs_code:
            if codes:
                for code in codes:
                    code_key = _fill_pattern(code_key_pattern, slug=slug, code=code, start=start)
                    add(
                        f"{target['label']}: Discount code {code}",
                        f"Merchant Center → Discounts → Discount codes → Add. "
                        f"Code: {code}. Key suggestion: {code_key}. "
                        f"Link it to the cart discount created above. "
                        f"Valid from {start or '…'} to {end or '…'}. "
                        f"{CODE_REQUIRED.get(code_required, 'Code required')}.",
                        code,
                    )
            else:
                add(
                    f"{target['label']}: Discount code",
                    "This activity expects a code, but none is listed yet. "
                    "Add the promo code under Measurement, save, then reopen this checklist. "
                    "Cart discount must exist before you create the code (Merchant Center CSV import covers codes only).",
                )

    if activity.get("product_scope") and not products:
        add(
            "Product range note",
            f"Free-text range on the activity: {activity['product_scope']}. "
            "Import the catalog in Settings and tick the SKUs to get a ready predicate.",
        )

    if not products and not (activity.get("product_scope") or "").strip():
        add(
            "Choose products",
            "No catalog SKUs are selected. Tick products on the activity (after importing the catalog in Settings), "
            "or write a category / brand predicate yourself in Merchant Center.",
        )

    missing = []
    if not (settings.get("cz_key") or "").strip() and (activity.get("shops") or "both") in {"both", "cz"}:
        missing.append("CZ store/project key")
    if not (settings.get("sk_key") or "").strip() and (activity.get("shops") or "both") in {"both", "sk"}:
        missing.append("SK store/project key")
    if audience == "registered" and not group_key:
        missing.append("registered customer group key")

    return {
        "type_label": type_label,
        "shops_label": SHOPS.get(activity.get("shops") or "both"),
        "audience_label": AUDIENCES.get(audience, AUDIENCES["all"]),
        "targets": targets,
        "predicate": predicate,
        "product_count": len(products),
        "steps": steps,
        "missing": missing,
        "settings_href": "/settings",
    }
