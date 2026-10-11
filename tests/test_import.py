from datetime import date

from studio.importer import header_is_pii, parse_date, parse_number, store_upload, suggest_mapping


def test_numbers_and_dates():
    assert parse_number("1.234,50") == 1234.50
    assert parse_number("1,234.50") == 1234.50
    assert parse_number("180,00") == 180
    assert parse_number("1 234,50") == 1234.50
    assert parse_number("CZK 180.00") == 180
    assert parse_number("") is None
    assert parse_date("2026-03-04T11:24:00Z") == date(2026, 3, 4)
    assert parse_date("09.10.2026") == date(2026, 10, 9)
    assert parse_date("03/04/2026") == date(2026, 4, 3)


def test_pii_headers_are_removed_before_the_file_is_kept(studio_env):
    raw = (studio_env / "orders.csv")
    raw.write_text(
        "order_number,created_at,customer_email\n1001,2026-03-01,parent@example.com\n",
        encoding="utf-8",
    )
    meta = store_upload("orders.csv", raw.read_bytes())
    pending = (studio_env / "inbox" / "pending.csv").read_text(encoding="utf-8")
    assert "parent@example.com" not in pending
    assert "customer_email" not in pending
    assert meta["pii_headers"] == ["customer_email"]
    assert header_is_pii("shipping_address")
    assert not header_is_pii("discount_code")


def test_suggest_mapping_prefers_the_code_over_the_discount_amount():
    chosen = suggest_mapping(
        ["order_number", "created_at", "order_state", "sku", "line_total", "discount", "discount_code", "currency"]
    )
    assert chosen["order_id"] == "order_number"
    assert chosen["promo_key"] == "discount_code"
    assert chosen["discount_amount"] == "discount"
    assert chosen["amount"] == "line_total"
