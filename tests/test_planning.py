from datetime import date

from studio.planning import longest_gap, month_rows, pack_lanes, year_timeline


def activity(name, start, end, status="planned"):
    return {
        "id": 1,
        "name": name,
        "status": status,
        "start_date": start,
        "end_date": end,
        "type_label": "Offer",
    }


def test_empty_year_has_no_gap_alert():
    assert longest_gap([], 2026) is None


def test_longest_open_stretch_follows_a_march_activity():
    start, end, days = longest_gap([activity("March", "2026-03-01", "2026-03-14")], 2026)
    assert start == date(2026, 3, 15)
    assert end == date(2026, 12, 31)
    assert days > 200


def test_march_bar_spans_the_right_weeks():
    rows = month_rows([activity("Welcome", "2026-03-08", "2026-03-28")], 2026, date(2026, 10, 9))
    march = rows[2]
    bar = march["lanes"][0][0]
    assert bar["col_start"] == 2
    assert bar["col_end"] == 5
    assert bar["shop_label"] == "CZ · SK"
    assert rows[0]["empty"] is True


def planned(name, start, end, activity_type="product_discount", shops="both", activity_id=1):
    return {
        "id": activity_id,
        "name": name,
        "status": "planned",
        "activity_type": activity_type,
        "shops": shops,
        "start_date": start,
        "end_date": end,
    }


def test_year_is_a_day_column_for_every_date():
    timeline = year_timeline([], 2026, date(2026, 10, 9))
    assert timeline["day_count"] == 365
    assert sum(month["days"] for month in timeline["months"]) == 365
    assert sum(week["days"] for week in timeline["weeks"]) == 365
    assert timeline["weeks"][0]["days"] == 4
    assert timeline["weeks"][0]["label"] == "1 Jan"
    assert len(timeline["rows"]) == 5
    assert timeline["rows"][0]["lanes"] == []
    october = timeline["days"][281]
    assert october["number"] == 9
    assert october["today"] is True


def test_a_march_activity_sits_on_its_type_row():
    timeline = year_timeline(
        [planned("Welcome", "2026-03-01", "2026-03-14")],
        2026,
        date(2026, 10, 9),
    )
    codes = timeline["rows"][0]
    bar = codes["lanes"][0][0]
    assert codes["key"] == "product_discount"
    assert bar["start"] == 59
    assert bar["span"] == 14
    assert timeline["rows"][1]["lanes"] == []


def test_same_type_overlaps_stack_and_other_types_stay_apart():
    timeline = year_timeline(
        [
            planned("Welcome", "2026-03-01", "2026-03-20", activity_id=1),
            planned("Spring", "2026-03-10", "2026-03-25", activity_id=2),
            planned("Trio", "2026-03-01", "2026-03-05", activity_type="multibuy", activity_id=3),
        ],
        2026,
        date(2026, 10, 9),
    )
    assert timeline["rows"][0]["lane_count"] == 2
    assert timeline["rows"][0]["meta"] == "2 activities"
    assert timeline["rows"][3]["key"] == "multibuy"
    assert timeline["rows"][3]["lane_count"] == 1


def test_shop_filter_keeps_shared_activities_on_both_storefronts():
    activities = [
        planned("Shared", "2026-04-01", "2026-04-10", shops="both", activity_id=1),
        planned("Czech only", "2026-04-01", "2026-04-10", shops="cz", activity_id=2),
        planned("Slovak only", "2026-04-01", "2026-04-10", activity_type="multibuy", shops="sk", activity_id=3),
    ]
    czech = year_timeline(activities, 2026, date(2026, 10, 9), shop="cz")
    names = {bar["name"] for row in czech["rows"] for lane in row["lanes"] for bar in lane}
    assert names == {"Shared", "Czech only"}
    slovak = year_timeline(activities, 2026, date(2026, 10, 9), shop="sk")
    slovak_names = {bar["name"] for row in slovak["rows"] for lane in row["lanes"] for bar in lane}
    assert slovak_names == {"Shared", "Slovak only"}


def test_a_bar_is_clipped_to_the_visible_year():
    timeline = year_timeline(
        [planned("New year", "2025-12-20", "2026-01-05")],
        2026,
        date(2026, 10, 9),
    )
    bar = timeline["rows"][0]["lanes"][0][0]
    assert bar["start"] == 0
    assert bar["span"] == 5


def test_overlapping_bars_use_separate_lanes():
    lanes = pack_lanes(
        [
            {"name": "A", "col_start": 1, "col_end": 3},
            {"name": "B", "col_start": 2, "col_end": 4},
            {"name": "C", "col_start": 3, "col_end": 5},
        ]
    )
    assert len(lanes) == 2
