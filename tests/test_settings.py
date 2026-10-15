from studio.catalog import apply_catalog_mapping, suggest_catalog_mapping
from studio.checklist import build_checklist
from studio.db import get_settings, list_catalog, session


def test_settings_page_saves_project_values(client):
    page = client.get("/settings")
    assert page.status_code == 200
    assert "Commercetools project" in page.text
    assert "Product catalog" in page.text

    saved = client.post(
        "/settings",
        data={
            "shop_model": "stores",
            "cz_key": "store-cz",
            "sk_key": "store-sk",
            "locale_cz": "cs-CZ",
            "locale_sk": "sk-SK",
            "currency_cz": "CZK",
            "currency_sk": "EUR",
            "predicate_style": "sku",
            "registered_customer_group_key": "registered",
            "key_pattern_cart": "cart-{slug}-{yyyy-mm}",
            "key_pattern_code": "code-{code}",
            "key_pattern_product": "product-{slug}-{yyyy-mm}",
            "default_sort_order": "0.7",
            "notes": "Always check stacking with shipping promos.",
        },
        follow_redirects=False,
    )
    assert saved.status_code == 303
    assert "saved=1" in saved.headers["location"]

    with session() as conn:
        settings = get_settings(conn)
    assert settings["cz_key"] == "store-cz"
    assert settings["sk_key"] == "store-sk"
    assert settings["default_sort_order"] == "0.7"
    assert "stacking" in settings["notes"]


def test_catalog_import_replace_and_activity_scope(client, tmp_path):
    csv_body = (
        "SKU;Product key;Name;Categories;Shops\n"
        "NK-001;p-nk-001;Nutri Start;infant;both\n"
        "NK-002;p-nk-002;Nutri Plus;follow-on;cz\n"
        "NK-003;p-nk-003;Nutri SK;follow-on;sk\n"
    ).encode("utf-8")
    upload = client.post(
        "/settings/catalog/upload",
        files={"file": ("catalog.csv", csv_body, "text/csv")},
        follow_redirects=False,
    )
    assert upload.status_code == 303

    mapping_page = client.get("/settings")
    assert "Store catalog" in mapping_page.text
    assert "NK-001" in mapping_page.text

    committed = client.post(
        "/settings/catalog/commit",
        data={
            "map_sku": "SKU",
            "map_product_key": "Product key",
            "map_variant_key": "",
            "map_name": "Name",
            "map_categories": "Categories",
            "map_shops": "Shops",
        },
        follow_redirects=False,
    )
    assert committed.status_code == 303
    assert "catalog_done=1" in committed.headers["location"]

    with session() as conn:
        products = list_catalog(conn)
    assert len(products) == 3
    assert {item["sku"] for item in products} == {"NK-001", "NK-002", "NK-003"}

    created = client.post(
        "/activities",
        data={
            "name": "Spring cart 15%",
            "activity_type": "cart_discount",
            "status": "planned",
            "start_date": "2026-04-01",
            "end_date": "2026-04-14",
            "notes": "",
            "shops": "both",
            "discount_kind": "percent",
            "discount_value": "15%",
            "code_required": "yes",
            "audience": "all",
            "match_keys": "SPRING15",
            "scope_sku": ["NK-001", "NK-002"],
            "year": "2026",
        },
        follow_redirects=False,
    )
    assert created.status_code == 303
    location = created.headers["location"]
    assert "activity=" in location

    modal = client.get(location)
    assert modal.status_code == 200
    assert "Merchant Center checklist" in modal.text
    assert "sku in" in modal.text
    assert "NK-001" in modal.text and "NK-002" in modal.text
    assert "Discount code SPRING15" in modal.text
    assert 'name="scope_sku" value="NK-001"' in modal.text
    assert "checked" in modal.text


def test_suggest_catalog_mapping_and_apply():
    headers = ["Variant SKU", "Product Key", "Title", "Category"]
    suggested = suggest_catalog_mapping(headers)
    assert suggested["sku"] == "Variant SKU"
    assert suggested["product_key"] == "Product Key"
    assert suggested["name"] == "Title"
    rows, skipped = apply_catalog_mapping(
        [
            {
                "Variant SKU": "A1",
                "Product Key": "p-a1",
                "Title": "Alpha",
                "Category": "cat-a",
            },
            {
                "Variant SKU": "",
                "Product Key": "p-skip",
                "Title": "Skip",
                "Category": "",
            },
        ],
        {
            "sku": "Variant SKU",
            "product_key": "Product Key",
            "name": "Title",
            "categories": "Category",
            "shops": "",
        },
    )
    assert skipped == 1
    assert rows == [
        {
            "sku": "A1",
            "product_key": "p-a1",
            "variant_key": "",
            "name": "Alpha",
            "categories": "cat-a",
            "shops": "both",
        }
    ]


def test_checklist_for_registered_cart_with_code():
    activity = {
        "name": "Member weekend",
        "activity_type": "cart_discount",
        "shops": "cz",
        "start_date": "2026-05-01",
        "end_date": "2026-05-03",
        "discount_kind": "percent",
        "discount_value": "10%",
        "code_required": "yes",
        "audience": "registered",
        "keys": ["MEMBER10"],
        "product_scope": "",
    }
    settings = {
        "shop_model": "stores",
        "cz_key": "cz",
        "sk_key": "sk",
        "locale_cz": "cs-CZ",
        "locale_sk": "sk-SK",
        "currency_cz": "CZK",
        "currency_sk": "EUR",
        "predicate_style": "sku",
        "registered_customer_group_key": "registered",
        "key_pattern_cart": "cart-{slug}-{yyyy-mm}",
        "key_pattern_code": "code-{code}",
        "key_pattern_product": "product-{slug}-{yyyy-mm}",
        "default_sort_order": "0.5",
        "notes": "",
    }
    products = [{"sku": "NK-001", "product_key": "p-nk-001"}]
    checklist = build_checklist(activity, settings, products)
    titles = [step["title"] for step in checklist["steps"]]
    assert any("Cart discount" in title for title in titles)
    assert any("Discount code MEMBER10" in title for title in titles)
    assert checklist["predicate"] == 'sku = "NK-001"'
    cart_step = next(step for step in checklist["steps"] if "Cart discount" in step["title"])
    assert "customer.customerGroup.key" in cart_step["detail"]
