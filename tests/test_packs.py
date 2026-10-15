from studio.packs import build_planning_packs, build_stock_ask, constraint_warnings


SETTINGS = {
    "shop_model": "stores",
    "cz_key": "cz",
    "sk_key": "sk",
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
    "blocked_skus": "NK-BAD\n",
    "blocked_categories": "infant-restricted",
    "min_gap_days": "7",
    "legal_checklist": "Confirm claims.\nConfirm gap.",
    "stacking_notes": "No free shipping with cart codes.",
    "default_stock_uplift": "1.5",
}


def test_blocked_sku_and_gap_warnings():
    activity = {
        "id": 2,
        "name": "Spring",
        "activity_type": "cart_discount",
        "shops": "both",
        "start_date": "2026-04-10",
        "end_date": "2026-04-20",
        "discount_kind": "percent",
        "discount_value": "15%",
        "skus": ["NK-BAD", "NK-001"],
        "keys": [],
        "product_scope": "",
    }
    products = [
        {"sku": "NK-BAD", "name": "Blocked", "categories": "adult"},
        {"sku": "NK-001", "name": "Ok", "categories": "adult"},
    ]
    others = [
        {
            "id": 1,
            "name": "Earlier",
            "status": "done",
            "shops": "cz",
            "start_date": "2026-04-01",
            "end_date": "2026-04-05",
            "skus": ["NK-001"],
        }
    ]
    warnings = constraint_warnings(activity, SETTINGS, products, others)
    codes = {item["code"] for item in warnings}
    assert "blocked_sku" in codes
    assert "gap" in codes


def test_stock_ask_formula():
    activity = {
        "name": "Bundle week",
        "start_date": "2026-05-01",
        "end_date": "2026-05-10",
        "shops": "both",
        "sku_lines": [
            {"sku": "A", "units_per_day": "10", "uplift": "", "ask_override": ""},
            {"sku": "B", "units_per_day": "2", "uplift": "2", "ask_override": ""},
        ],
    }
    products = [
        {"sku": "A", "name": "Alpha", "categories": ""},
        {"sku": "B", "name": "Beta", "categories": ""},
    ]
    stock = build_stock_ask(activity, SETTINGS, products)
    # A: 10 days × 10 × 1.5 = 150; B: 10 × 2 × 2 = 40
    assert stock["days"] == 10
    assert stock["lines"][0]["ask"] == 150
    assert stock["lines"][1]["ask"] == 40
    assert stock["total"] == 190
    assert "Alpha" in stock["copy_text"]


def test_stock_ask_uses_past_sales_when_units_blank():
    activity = {
        "name": "From sales",
        "start_date": "2026-06-01",
        "end_date": "2026-06-10",
        "shops": "both",
        "sku_lines": [
            {"sku": "A", "units_per_day": "", "uplift": "", "ask_override": ""},
        ],
    }
    products = [{"sku": "A", "name": "Alpha", "categories": ""}]
    stock = build_stock_ask(
        activity,
        SETTINGS,
        products,
        sales_rates={"A": 4.0},
        sales_window=("2026-05-01", "2026-05-28"),
    )
    # 4/day × 10 days × 1.5 uplift = 60
    assert stock["lines"][0]["ask"] == 60
    assert stock["lines"][0]["past_rate"] == 4.0
    assert "past sales" in stock["lines"][0]["method"]


def test_planning_packs_include_all_outputs(client):
    client.post(
        "/settings",
        data={
            "shop_model": "stores",
            "cz_key": "cz",
            "sk_key": "sk",
            "locale_cz": "cs-CZ",
            "locale_sk": "sk-SK",
            "currency_cz": "CZK",
            "currency_sk": "EUR",
            "predicate_style": "sku",
            "min_gap_days": "7",
            "blocked_skus": "",
            "blocked_categories": "",
            "legal_checklist": "Check claims",
            "stacking_notes": "",
            "default_stock_uplift": "1.2",
            "default_sort_order": "0.5",
            "notes": "",
        },
        follow_redirects=False,
    )
    # seed catalog via replace path is heavy; packs work without catalog products in unit path
    packs = build_planning_packs(
        {
            "name": "May gift",
            "activity_type": "gift",
            "shops": "cz",
            "start_date": "2026-05-01",
            "end_date": "2026-05-07",
            "discount_kind": "free",
            "discount_value": "Gift pouch",
            "objective": "Raise AOV",
            "asset_notes": "Warm tone",
            "asset_options": "homepage_cz,legal_disclaimer",
            "code_required": "no",
            "audience": "all",
            "keys": [],
            "sku_lines": [
                {"sku": "G1", "units_per_day": "5", "uplift": "2", "ask_override": ""},
            ],
            "product_scope": "",
            "offer_json": "{}",
        },
        SETTINGS,
        [{"sku": "G1", "name": "Gift", "categories": "gifts", "product_key": ""}],
        [],
    )
    assert packs["stock"]["lines"][0]["ask"] == 70  # 7 days * 5 * 2
    assert "Asset brief" in packs["assets"]["copy_text"]
    assert "Warm tone" in packs["assets"]["copy_text"]
    assert "Homepage banner — CZ" in packs["assets"]["copy_text"]
    assert packs["legal"]["checks"]
    assert packs["checklist"]["steps"]


def test_activity_modal_shows_planning_packs(client):
    created = client.post(
        "/activities",
        data={
            "name": "Packs demo",
            "activity_type": "cart_discount",
            "status": "planned",
            "start_date": "2026-06-01",
            "end_date": "2026-06-07",
            "objective": "Clear spring stock",
            "discount_kind": "percent",
            "discount_value": "20%",
            "stock_units_per_day": "3",
            "shops": "both",
            "year": "2026",
        },
        follow_redirects=False,
    )
    modal = client.get(created.headers["location"])
    assert modal.status_code == 200
    assert "Planning packs" in modal.text or 'data-pack-tab="stock"' in modal.text
    assert "Stock ask" in modal.text
    assert "Asset brief" in modal.text
    assert "Legal / compliance" in modal.text
    assert "Campaign rules" in client.get("/settings").text
