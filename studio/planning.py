from __future__ import annotations

from calendar import monthrange
from datetime import date, timedelta

from studio.constants import SHOP_SHORT, TYPES
from studio.formatting import format_days, format_range, inclusive_days


def week_index(day: int) -> int:
    if day <= 7:
        return 1
    if day <= 14:
        return 2
    if day <= 21:
        return 3
    return 4


def _parse(value: str) -> date:
    return date.fromisoformat(value[:10])


def pack_lanes(bars: list[dict]) -> list[list[dict]]:
    ordered = sorted(bars, key=lambda bar: (bar["col_start"], bar["col_end"], bar["name"]))
    lanes: list[list[dict]] = []
    for bar in ordered:
        for lane in lanes:
            if all(bar["col_start"] >= other["col_end"] or bar["col_end"] <= other["col_start"] for other in lane):
                lane.append(bar)
                break
        else:
            lanes.append([bar])
    return lanes


def month_rows(activities: list[dict], year: int, today: date) -> list[dict]:
    rows = []
    for month in range(1, 13):
        first = date(year, month, 1)
        last_day = monthrange(year, month)[1]
        last = date(year, month, last_day)
        bars = []
        for activity in activities:
            start = _parse(activity["start_date"])
            end = _parse(activity["end_date"])
            if end < first or start > last:
                continue
            clipped_start = max(start, first)
            clipped_end = min(end, last)
            shops = activity.get("shops") or "both"
            bars.append(
                {
                    "id": activity["id"],
                    "name": activity["name"],
                    "status": activity["status"],
                    "type_label": activity.get("type_label", ""),
                    "shops": shops,
                    "shop_label": SHOP_SHORT.get(shops, SHOP_SHORT["both"]),
                    "href": f"/activities/{activity['id']}",
                    "col_start": week_index(clipped_start.day),
                    "col_end": week_index(clipped_end.day) + 1,
                    "dates": format_range(start, end),
                }
            )
        count = len(bars)
        if count == 0:
            load = "—"
        elif count == 1:
            load = "1 activity"
        else:
            load = f"{count} activities"
        today_pct = None
        if today.year == year and today.month == month:
            today_pct = round((today.day - 0.5) / last_day * 100, 2)
        rows.append(
            {
                "name": first.strftime("%b"),
                "index": f"{month:02d}",
                "lanes": pack_lanes(bars),
                "load": load,
                "empty": count == 0,
                "today_pct": today_pct,
            }
        )
    return rows


def covering_activities(activities: list[dict]) -> list[dict]:
    return [activity for activity in activities if activity["status"] != "cancelled"]


def longest_gap(activities: list[dict], year: int) -> tuple[date, date, int] | None:
    active = covering_activities(activities)
    if not active:
        return None
    covered = set()
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    for activity in active:
        start = max(_parse(activity["start_date"]), year_start)
        end = min(_parse(activity["end_date"]), year_end)
        if end < start:
            continue
        day = start
        while day <= end:
            covered.add(day)
            day += timedelta(days=1)
    best: tuple[date, date] | None = None
    run_start = None
    day = year_start
    while day <= year_end:
        if day not in covered:
            if run_start is None:
                run_start = day
        elif run_start is not None:
            run_end = day - timedelta(days=1)
            if best is None or (run_end - run_start) > (best[1] - best[0]):
                best = (run_start, run_end)
            run_start = None
        day += timedelta(days=1)
    if run_start is not None:
        if best is None or (year_end - run_start) > (best[1] - best[0]):
            best = (run_start, year_end)
    if best is None:
        return None
    length = inclusive_days(best[0], best[1])
    if length < 7:
        return None
    return best[0], best[1], length


def year_summary(activities: list[dict], year: int) -> dict | None:
    active = covering_activities(activities)
    if not active:
        return None
    year_start = date(year, 1, 1)
    year_end = date(year, 12, 31)
    covered = set()
    durations = []
    for activity in active:
        start = _parse(activity["start_date"])
        end = _parse(activity["end_date"])
        durations.append(inclusive_days(start, end))
        clipped_start = max(start, year_start)
        clipped_end = min(end, year_end)
        if clipped_end < clipped_start:
            continue
        day = clipped_start
        while day <= clipped_end:
            covered.add(day)
            day += timedelta(days=1)
    gap = longest_gap(activities, year)
    return {
        "activity_count": len(active),
        "days_active": len(covered),
        "average_duration": format_days(sum(durations) / len(durations)),
        "gap": None
        if gap is None
        else {"start": gap[0], "end": gap[1], "days": gap[2], "label": format_range(gap[0], gap[1])},
    }


def next_activity(activities: list[dict], today: date) -> dict | None:
    today_text = today.isoformat()
    candidates = [
        activity
        for activity in activities
        if activity["status"] in {"planned", "live"} and activity["end_date"] >= today_text
    ]
    if not candidates:
        return None
    candidates.sort(key=lambda activity: (activity["start_date"], activity["name"]))
    chosen = candidates[0]
    start = _parse(chosen["start_date"])
    end = _parse(chosen["end_date"])
    if start <= today <= end:
        lead = f"In progress, through {format_range(start, end)}"
    else:
        days = (start - today).days
        lead = f"Begins in {format_days(days)} ({format_range(start, end)})"
    return {**chosen, "lead": lead}


def date_overlaps(activity: dict, activities: list[dict]) -> list[dict]:
    start = _parse(activity["start_date"])
    end = _parse(activity["end_date"])
    found = []
    for other in activities:
        if other["id"] == activity["id"] or other["status"] == "cancelled":
            continue
        other_start = _parse(other["start_date"])
        other_end = _parse(other["end_date"])
        if other_start <= end and other_end >= start:
            found.append(other)
    found.sort(key=lambda item: item["start_date"])
    return found


def similar_activities(activity: dict, activities: list[dict], limit: int = 3) -> list[dict]:
    others = [
        item
        for item in activities
        if item["id"] != activity["id"] and item["activity_type"] == activity["activity_type"]
    ]
    done = [item for item in others if item["status"] == "done"]
    rest = [item for item in others if item["status"] != "done"]
    done.sort(key=lambda item: item["end_date"], reverse=True)
    rest.sort(key=lambda item: item["end_date"], reverse=True)
    return (done + rest)[:limit]


def runs_on_shop(activity: dict, shop: str) -> bool:
    shops = activity.get("shops") or "both"
    if shop in {"", "all"}:
        return True
    if shop == "cz":
        return shops in {"both", "cz"}
    if shop == "sk":
        return shops in {"both", "sk"}
    return True


def same_storefront(left: dict, right: dict) -> bool:
    a = left.get("shops") or "both"
    b = right.get("shops") or "both"
    if a == "both" or b == "both":
        return True
    return a == b


def pack_day_lanes(bars: list[dict]) -> list[list[dict]]:
    ordered = sorted(bars, key=lambda bar: (bar["start"], bar["end"], bar["name"].casefold()))
    lanes: list[list[dict]] = []
    for bar in ordered:
        for lane in lanes:
            if all(bar["start"] >= other["end"] or bar["end"] <= other["start"] for other in lane):
                lane.append(bar)
                break
        else:
            lanes.append([bar])
    return lanes


def _row_meta(count: int) -> str:
    if count == 0:
        return "None"
    if count == 1:
        return "1 activity"
    return f"{count} activities"


def year_timeline(activities: list[dict], year: int, today: date, shop: str = "all") -> dict:
    start = date(year, 1, 1)
    end = date(year, 12, 31)
    days = []
    months = []
    month_name = ""
    month_days = 0
    month_start = 0
    current = start
    while current <= end:
        if current.day == 1:
            if month_days:
                months.append({"name": month_name, "days": month_days, "start": month_start})
            month_name = current.strftime("%B")
            month_days = 0
            month_start = (current - start).days
        days.append(
            {
                "index": (current - start).days,
                "number": current.day,
                "weekday": "MTWTFSS"[current.weekday()],
                "weekend": current.weekday() >= 5,
                "today": current == today,
                "month_start": current.day == 1,
            }
        )
        month_days += 1
        current += timedelta(days=1)
    months.append({"name": month_name, "days": month_days, "start": month_start})

    weeks = []
    week_start = 0
    for index, day in enumerate(days):
        current_day = start + timedelta(days=index)
        if current_day.weekday() == 6 or index == len(days) - 1:
            first = start + timedelta(days=week_start)
            weeks.append(
                {
                    "label": f"{first.day} {first.strftime('%b')}",
                    "days": index - week_start + 1,
                    "start": week_start,
                }
            )
            week_start = index + 1

    visible = [activity for activity in activities if runs_on_shop(activity, shop)]
    rows = []
    for key, label in TYPES.items():
        bars = []
        for activity in visible:
            if activity["activity_type"] != key:
                continue
            activity_start = _parse(activity["start_date"])
            activity_end = _parse(activity["end_date"])
            clipped_start = max(activity_start, start)
            clipped_end = min(activity_end, end)
            if clipped_end < clipped_start:
                continue
            start_index = (clipped_start - start).days
            span = inclusive_days(clipped_start, clipped_end)
            shops = activity.get("shops") or "both"
            bars.append(
                {
                    "id": activity["id"],
                    "name": activity["name"],
                    "status": activity["status"],
                    "shops": shops,
                    "shop_label": SHOP_SHORT.get(shops, SHOP_SHORT["both"]),
                    "href": f"/activities/{activity['id']}",
                    "dates": format_range(activity_start, activity_end),
                    "start": start_index,
                    "end": start_index + span,
                    "span": span,
                }
            )
        lanes = pack_day_lanes(bars)
        rows.append(
            {
                "key": key,
                "label": label,
                "count": len(bars),
                "lanes": lanes,
                "lane_count": len(lanes),
                "meta": _row_meta(len(bars)),
            }
        )
    return {
        "day_count": len(days),
        "days": days,
        "months": months,
        "weeks": weeks,
        "rows": rows,
        "today_index": (today - start).days if start <= today <= end else None,
    }


def filter_activities(activities: list[dict], status: str, when: str, activity_type: str, query: str, today: date) -> list[dict]:
    today_text = today.isoformat()
    needle = query.casefold().strip()
    chosen = []
    for activity in activities:
        if status != "all" and activity["status"] != status:
            continue
        if activity_type != "all" and activity["activity_type"] != activity_type:
            continue
        upcoming = activity["end_date"] >= today_text and activity["status"] in {"draft", "planned", "live"}
        past = activity["end_date"] < today_text or activity["status"] in {"done", "cancelled"}
        if when == "upcoming" and not upcoming:
            continue
        if when == "past" and not past:
            continue
        if needle:
            haystack = " ".join([activity["name"], activity["notes"], *activity["keys"]]).casefold()
            if needle not in haystack:
                continue
        chosen.append(activity)
    return chosen
