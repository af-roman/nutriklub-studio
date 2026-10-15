TYPES = {
    "product_discount": "Product discount",
    "cart_discount": "Cart discount",
    "shipping_discount": "Shipping discount",
    "multibuy": "Multibuy",
    "gift": "Gift",
}

TYPE_ALIASES = {
    "discount_code": "product_discount",
    "offer": "product_discount",
    "bundle": "multibuy",
    "campaign": "product_discount",
    "other": "product_discount",
}

STATUSES = {
    "draft": "Draft",
    "planned": "Planned",
    "live": "Live",
    "done": "Done",
    "cancelled": "Cancelled",
}

SHOPS = {
    "both": "Czechia and Slovakia",
    "cz": "Czechia only",
    "sk": "Slovakia only",
}

SHOP_SHORT = {
    "both": "CZ · SK",
    "cz": "CZ",
    "sk": "SK",
}

DISCOUNT_KINDS = {
    "": "Not set",
    "percent": "Percent off",
    "amount": "Fixed amount off",
    "free": "Free item or shipping",
    "other": "Other",
}

AUDIENCES = {
    "all": "All visitors",
    "registered": "Registered users only",
}

CODE_REQUIRED = {
    "": "Not set",
    "yes": "Yes, a code is required",
    "no": "No code needed",
}

IMPORT_FIELDS = [
    ("order_id", "Order ID", "Unique order reference", True),
    ("line_id", "Line ID", "Set this when the file has one row per product", False),
    ("order_date", "Order date", "Day the order was placed", True),
    ("status", "Order status", "Used to leave cancelled orders out of a reading", False),
    ("sku", "SKU", "Product code. The baseline uses the same products", False),
    ("product_name", "Product name", "Name as it appears on the order", False),
    ("quantity", "Quantity", "Units on the row", False),
    ("amount", "Amount", "Value of the row, as exported", False),
    ("discount_amount", "Discount amount", "Discount on the row, as exported", False),
    ("currency", "Currency", "Mixed currencies are kept apart", False),
    ("promo_key", "Promo code or name", "Matched to the code written on an activity", False),
]

CATALOG_FIELDS = [
    ("sku", "SKU", "Variant SKU used in predicates and orders", True),
    ("product_key", "Product key", "Commercetools product key", False),
    ("variant_key", "Variant key", "Commercetools variant key", False),
    ("name", "Product name", "Human-readable name for search", False),
    ("categories", "Categories", "Category keys or names, separated by ;", False),
    ("shops", "Shops", "both, cz, or sk. Empty means both", False),
]

SHOP_MODELS = {
    "stores": "One project, two Stores (CZ and SK)",
    "projects": "Two separate projects (CZ and SK)",
}

ASSET_OPTIONS = {
    "homepage_cz": "Homepage banner — CZ",
    "homepage_sk": "Homepage banner — SK",
    "plp_tile": "Category / PLP tile",
    "pdp_strip": "Product detail strip",
    "cart_banner": "Cart / checkout banner",
    "email_module": "Email / SFMC module",
    "social_cutdown": "Social cutdown",
    "legal_disclaimer": "Include legal disclaimer line",
    "price_from_claim": "Include “from / price” claim check",
    "code_callout": "Show promo code callout",
}

DEFAULT_SETTINGS = {
    "shop_model": "stores",
    "cz_key": "",
    "sk_key": "",
    "locale_cz": "cs-CZ",
    "locale_sk": "sk-SK",
    "currency_cz": "CZK",
    "currency_sk": "EUR",
    "predicate_style": "sku",
    "registered_customer_group_key": "",
    "key_pattern_cart": "cart-{slug}-{yyyy-mm}",
    "key_pattern_code": "code-{code}",
    "key_pattern_product": "product-{slug}-{yyyy-mm}",
    "default_sort_order": "0.5",
    "notes": "",
    "blocked_skus": "",
    "blocked_categories": "",
    "min_gap_days": "7",
    "legal_checklist": (
        "Confirm the offer text matches the mechanic and rate.\n"
        "Confirm no blocked products or categories are included.\n"
        "Confirm the gap to the previous promo on the same SKUs is acceptable.\n"
        "Confirm CZ and SK copy / pricing are correct for each shop."
    ),
    "stacking_notes": "",
    "default_stock_uplift": "1.3",
}
