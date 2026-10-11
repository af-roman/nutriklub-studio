import math
from pathlib import Path

from studio.db import create_activity, get_activity, replace_orders, session
from studio.importer import apply_mapping, load_pending_rows, store_upload, suggest_mapping
from studio.scoring import score_activity, shared_product_ids


def meta(filename="orders.csv", row_count=1):
    return {
        "filename": filename,
        "row_count": row_count,
        "grain": "order",
        "has_quantity": True,
        "has_amount": True,
        "has_discount": True,
        "skipped_rows": 0,
    }


def line(**kwargs):
    record = {
        "order_id": "1",
        "line_id": "",
        "order_date": "2026-03-01",
        "status": "Complete",
        "cancelled": False,
        "sku": "A",
        "product_name": "Item",
        "quantity": 1,
        "amount": 100,
        "discount_amount": 0,
        "currency": "CZK",
        "promos": ["CODE"],
    }
    record.update(kwargs)
    return record


def save_activity(**kwargs):
    fields = {
        "name": "Code",
        "activity_type": "discount_code",
        "status": "done",
        "start_date": "2026-03-01",
        "end_date": "2026-03-10",
        "notes": "",
        "baseline_start": "2026-02-01",
        "baseline_end": "2026-02-05",
        "keys": ["CODE"],
    }
    fields.update(kwargs)
    keys = fields.pop("keys")
    with session() as conn:
        activity_id = create_activity(conn, fields, keys)
    return activity_id


def test_per_day_comparison_when_windows_differ_in_length():
    with session() as conn:
        replace_orders(
            conn,
            [
                line(order_id="A", order_date="2026-03-01", amount=100, promos=["CODE"]),
                line(order_id="B", order_date="2026-02-01", amount=100, promos=[]),
            ],
            meta(row_count=2),
        )
    activity_id = save_activity()
    with session() as conn:
        score = score_activity(conn, get_activity(conn, activity_id))
    assert math.isclose(score.figures[0].revenue.delta_ratio, -0.5)
    assert score.figures[0].revenue.total == 100
    assert score.figures[0].revenue.baseline_total == 100


def test_sample_file_matches_welcome_code_and_drops_email(studio_env):
    raw = Path("fixtures/orders_sample.csv").read_bytes()
    store_upload("orders_sample.csv", raw)
    pending = (studio_env / "inbox" / "pending.csv").read_text(encoding="utf-8")
    assert "parent@example.com" not in pending
    rows, skipped = apply_mapping(load_pending_rows(), suggest_mapping(
        ["order_number", "created_at", "order_state", "sku", "product_name", "quantity", "line_total", "discount", "currency", "discount_code"]
    ))
    assert skipped == 0
    with session() as conn:
        replace_orders(conn, rows, meta("orders_sample.csv", len(rows)))
        create_activity(
            conn,
            {
                "name": "Welcome code, 15% — March",
                "activity_type": "discount_code",
                "status": "done",
                "start_date": "2026-03-01",
                "end_date": "2026-03-14",
                "notes": "",
                "baseline_start": "2026-02-01",
                "baseline_end": "2026-02-14",
            },
            ["WELCOME15"],
        )
        score = score_activity(conn, get_activity(conn, 1))
    assert score.state == "ok"
    assert score.figures[0].revenue.total == 540
    assert score.figures[0].revenue.baseline_total == 400
    assert math.isclose(score.figures[0].revenue.delta_ratio, 0.35)
    assert score.figures[0].orders.total == 3
    assert score.figures[0].units.total == 6
    assert score.figures[0].discount.total == 60
    assert b"parent@example.com" not in Path(studio_env / "studio.db").read_bytes()


def test_cancelled_other_code_and_other_sku_stay_out_of_the_reading():
    with session() as conn:
        replace_orders(
            conn,
            [
                line(order_id="ok", amount=180, quantity=2, discount_amount=20),
                line(order_id="void", amount=999, cancelled=True, status="Cancelled"),
                line(order_id="other", amount=50, promos=["ELSE"]),
                line(order_id="bottle", order_date="2026-02-02", amount=999, sku="B", promos=[]),
            ],
            meta(row_count=4),
        )
        create_activity(
            conn,
            {
                "name": "Code",
                "activity_type": "discount_code",
                "status": "done",
                "start_date": "2026-03-01",
                "end_date": "2026-03-10",
                "notes": "",
                "baseline_start": "2026-02-01",
                "baseline_end": "2026-02-10",
            },
            ["CODE"],
        )
        score = score_activity(conn, get_activity(conn, 1))
    assert score.figures[0].revenue.total == 180
    assert score.figures[0].revenue.baseline_total == 0


def test_mixed_currencies_are_not_added():
    with session() as conn:
        replace_orders(
            conn,
            [
                line(order_id="cz", amount=100, currency="CZK"),
                line(order_id="eu", amount=50, currency="EUR"),
            ],
            meta(row_count=2),
        )
        create_activity(
            conn,
            {
                "name": "Code",
                "activity_type": "discount_code",
                "status": "done",
                "start_date": "2026-03-01",
                "end_date": "2026-03-10",
                "notes": "",
                "baseline_start": None,
                "baseline_end": None,
            },
            ["CODE"],
        )
        score = score_activity(conn, get_activity(conn, 1))
    assert score.state == "mixed"
    totals = sorted(figure.revenue.total for figure in score.figures)
    assert totals == [50, 100]


def test_missing_code_is_not_a_failed_activity():
    with session() as conn:
        replace_orders(conn, [line(promos=["OTHER"])], meta())
        create_activity(
            conn,
            {
                "name": "Code",
                "activity_type": "discount_code",
                "status": "done",
                "start_date": "2026-03-01",
                "end_date": "2026-03-10",
                "notes": "",
                "baseline_start": None,
                "baseline_end": None,
            },
            ["CODE"],
        )
        score = score_activity(conn, get_activity(conn, 1))
    assert score.state == "no_match"
    assert score.figures == []


def test_shared_products_are_named_on_an_overlap():
    with session() as conn:
        replace_orders(
            conn,
            [
                line(order_id="a", order_date="2026-03-05", promos=["WELCOME15"]),
                line(order_id="b", order_date="2026-03-12", promos=["OTHER"]),
            ],
            meta(row_count=2),
        )
        first = create_activity(
            conn,
            {
                "name": "Welcome",
                "activity_type": "discount_code",
                "status": "done",
                "start_date": "2026-03-01",
                "end_date": "2026-03-20",
                "notes": "",
                "baseline_start": None,
                "baseline_end": None,
            },
            ["WELCOME15"],
        )
        second = create_activity(
            conn,
            {
                "name": "Other",
                "activity_type": "offer",
                "status": "done",
                "start_date": "2026-03-10",
                "end_date": "2026-03-31",
                "notes": "",
                "baseline_start": None,
                "baseline_end": None,
            },
            ["OTHER"],
        )
        from studio.db import list_activities

        welcome = get_activity(conn, first)
        shared = shared_product_ids(conn, welcome, list_activities(conn))
    assert shared == {second}
