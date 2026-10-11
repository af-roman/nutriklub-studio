from pathlib import Path


WELCOME = {
    "name": "Welcome code, 15% — March",
    "activity_type": "product_discount",
    "status": "done",
    "start_date": "2026-03-01",
    "end_date": "2026-03-14",
    "notes": "First checkout for new subscribers.",
    "baseline_start": "2026-02-01",
    "baseline_end": "2026-02-14",
    "match_keys": "WELCOME15",
    "year": "2026",
}


def test_empty_plan_invites_an_activity_before_any_file(client):
    page = client.get("/?year=2026")
    assert page.status_code == 200
    assert "The year is open" in page.text
    assert "Add the first activity" in page.text
    assert "year-scroll" in page.text
    assert "Product discount" in page.text
    assert "upload orders first" not in page.text.lower()
    assert 'aria-label="View"' in page.text
    assert 'aria-label="Shop"' in page.text
    assert ">Activity<" not in page.text
    assert page.text.count("New activity") == 1
    form = client.get("/?year=2026&activity=new")
    assert form.status_code == 200
    assert "activity-modal" in form.text
    assert "Czechia and Slovakia" in form.text
    assert "Czechia only" in form.text
    assert "Slovakia only" in form.text
    assert "Product range note" in form.text
    assert "Merchant Center checklist" in form.text
    assert "Registered users only" in form.text
    assert 'href="/settings"' in page.text
    assert "calendar.js" in page.text
    redirected = client.get("/activities/new?year=2026", follow_redirects=False)
    assert redirected.status_code == 303
    assert "activity=new" in redirected.headers["location"]


def test_months_view_marks_each_shop(client):
    client.post(
        "/activities",
        data={**WELCOME, "name": "Slovak months", "shops": "sk", "status": "planned"},
        follow_redirects=False,
    )
    client.post(
        "/activities",
        data={**WELCOME, "name": "Shared months", "shops": "both", "status": "planned"},
        follow_redirects=False,
    )
    page = client.get("/?year=2026&view=months")
    assert page.status_code == 200
    assert "Week 1 · 1–7" in page.text
    assert "year-scroll" not in page.text
    assert "shop-sk" in page.text
    assert "shop-both" in page.text
    assert "SK · Product discount" in page.text
    czech = client.get("/?year=2026&view=months&shop=cz")
    assert "Slovak months" not in czech.text
    assert "Shared months" in czech.text
    assert "view=months" in czech.text


def test_shop_filter_hides_the_other_storefront(client):
    client.post(
        "/activities",
        data={**WELCOME, "name": "Slovak bundle", "activity_type": "multibuy", "shops": "sk", "status": "planned"},
        follow_redirects=False,
    )
    client.post(
        "/activities",
        data={**WELCOME, "name": "Shared code", "shops": "both", "status": "planned"},
        follow_redirects=False,
    )
    czech = client.get("/?year=2026&shop=cz")
    assert "Slovak bundle" not in czech.text
    assert "Shared code" in czech.text
    slovak = client.get("/?year=2026&shop=sk")
    assert "Slovak bundle" in slovak.text
    assert "Shared code" in slovak.text
    ledger = client.get("/?year=2026&view=list&shop=cz")
    assert "Slovak bundle" not in ledger.text
    assert "CZ · SK" in ledger.text


def test_older_database_gains_a_shops_column(studio_env):
    import sqlite3

    from studio.db import get_activity, session

    path = studio_env / "studio.db"
    conn = sqlite3.connect(path)
    conn.execute(
        """
        CREATE TABLE activities (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            status TEXT NOT NULL,
            start_date TEXT NOT NULL,
            end_date TEXT NOT NULL,
            notes TEXT NOT NULL DEFAULT '',
            baseline_start TEXT,
            baseline_end TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        INSERT INTO activities (
            name, activity_type, status, start_date, end_date, created_at, updated_at
        ) VALUES ('Old offer', 'offer', 'draft', '2026-05-01', '2026-05-10', 't', 't')
        """
    )
    conn.commit()
    conn.close()
    with session() as conn:
        activity = get_activity(conn, 1)
    assert activity["shops"] == "both"
    assert activity["activity_type"] == "product_discount"
    assert activity["audience"] == "all"


def test_schedule_endpoint_moves_an_activity(client):
    created = client.post("/activities", data=WELCOME, follow_redirects=False)
    activity_id = created.headers["location"].rsplit("activity=", 1)[-1]
    moved = client.post(
        f"/activities/{activity_id}/schedule",
        data={"start_date": "2026-04-01", "end_date": "2026-04-14"},
    )
    assert moved.status_code == 200
    assert moved.json()["ok"] is True
    assert moved.json()["start_date"] == "2026-04-01"
    assert moved.json()["end_date"] == "2026-04-14"
    page = client.get(f"/?year=2026&activity={activity_id}")
    assert 'value="2026-04-01"' in page.text
    assert 'value="2026-04-14"' in page.text


def test_a_saved_activity_appears_on_the_plan(client):
    created = client.post("/activities", data=WELCOME, follow_redirects=False)
    assert created.status_code == 303
    assert "activity=1" in created.headers["location"]
    activity = client.get(created.headers["location"])
    assert "Welcome code, 15% — March" in activity.text
    assert "activity-modal" in activity.text
    plan = client.get("/?year=2026")
    assert "Welcome code, 15% — March" in plan.text
    assert "activity=1" in plan.text
    ledger = client.get("/?year=2026&view=list")
    assert "Welcome code, 15% — March" in ledger.text


def test_import_and_scorecard_round_trip(client, studio_env):
    raw = Path("fixtures/orders_sample.csv").read_bytes()
    uploaded = client.post(
        "/import/upload",
        files={"file": ("orders.csv", raw, "text/csv")},
        follow_redirects=False,
    )
    assert uploaded.status_code == 303
    preview = client.get("/import")
    assert preview.status_code == 200
    assert "parent@example.com" not in preview.text
    assert "customer_email" in preview.text
    assert b"parent@example.com" not in (studio_env / "inbox" / "pending.csv").read_bytes()

    stored = client.post(
        "/import/commit",
        data={
            "map_order_id": "order_number",
            "map_order_date": "created_at",
            "map_status": "order_state",
            "map_sku": "sku",
            "map_product_name": "product_name",
            "map_quantity": "quantity",
            "map_amount": "line_total",
            "map_discount_amount": "discount",
            "map_currency": "currency",
            "map_promo_key": "discount_code",
            "map_line_id": "",
        },
        follow_redirects=False,
    )
    assert stored.status_code == 303
    done = client.get(stored.headers["location"])
    assert "11 orders" in done.text
    assert "parent@example.com" not in done.text

    created = client.post("/activities", data=WELCOME, follow_redirects=False)
    page = client.get(created.headers["location"])
    assert "540.00 CZK" in page.text
    assert "35% above the baseline" in page.text
    assert "does not show that the activity caused the difference" in page.text
    assert "parent@example.com" not in page.text
    plan = client.get("/?year=2026")
    assert "revenue per day 35% above baseline" in plan.text
