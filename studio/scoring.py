from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field
from datetime import date, timedelta

from studio.formatting import format_range, format_timestamp, inclusive_days


@dataclass
class Measure:
    total: float | None
    per_day: float | None
    baseline_total: float | None
    baseline_per_day: float | None
    delta_ratio: float | None


@dataclass
class CurrencyFigures:
    currency: str
    revenue: Measure
    orders: Measure
    units: Measure
    discount: Measure
    spark_points: str = ""


@dataclass
class Score:
    state: str
    message: str
    notes: list[str] = field(default_factory=list)
    figures: list[CurrencyFigures] = field(default_factory=list)
    keys_found: list[str] = field(default_factory=list)
    keys_missing: list[str] = field(default_factory=list)


def _days(start: str, end: str) -> int:
    return inclusive_days(date.fromisoformat(start), date.fromisoformat(end))


def _per_day(total: float | None, days: int) -> float | None:
    if total is None:
        return None
    return total / days


def _delta(current: float | None, baseline: float | None) -> float | None:
    if current is None or baseline is None or baseline == 0:
        return None
    return (current - baseline) / baseline


def _sum(values: list[float | None]) -> float | None:
    present = [value for value in values if value is not None]
    if not present:
        return None
    return float(sum(present))


def _measure(lines: list[dict], field_name: str, days: int, baseline_lines: list[dict] | None, baseline_days: int | None) -> Measure:
    total = _sum([line[field_name] for line in lines])
    baseline_total = None
    baseline_per_day = None
    if baseline_lines is not None and baseline_days:
        baseline_total = _sum([line[field_name] for line in baseline_lines])
        if baseline_total is None and not baseline_lines:
            baseline_total = 0.0 if total is not None else None
        baseline_per_day = _per_day(baseline_total, baseline_days)
    return Measure(
        total=total,
        per_day=_per_day(total, days),
        baseline_total=baseline_total,
        baseline_per_day=baseline_per_day,
        delta_ratio=_delta(_per_day(total, days), baseline_per_day),
    )


def _order_measure(lines: list[dict], days: int, baseline_lines: list[dict] | None, baseline_days: int | None) -> Measure:
    total = float(len({line["order_id"] for line in lines}))
    baseline_total = None
    baseline_per_day = None
    if baseline_lines is not None and baseline_days:
        baseline_total = float(len({line["order_id"] for line in baseline_lines}))
        baseline_per_day = baseline_total / baseline_days
    return Measure(
        total=total,
        per_day=total / days,
        baseline_total=baseline_total,
        baseline_per_day=baseline_per_day,
        delta_ratio=_delta(total / days, baseline_per_day),
    )


def _spark(lines: list[dict], start: str, end: str) -> str:
    totals: dict[str, float] = {}
    for line in lines:
        if line["amount"] is None:
            continue
        totals[line["order_date"]] = totals.get(line["order_date"], 0.0) + line["amount"]
    if not totals:
        return ""
    values = []
    day = date.fromisoformat(start)
    last = date.fromisoformat(end)
    while day <= last:
        values.append(totals.get(day.isoformat(), 0.0))
        day += timedelta(days=1)
    if len(values) < 2:
        return ""
    low = min(values)
    high = max(values)
    span = high - low or 1
    width, height = 160, 36
    parts = []
    last_index = len(values) - 1
    for index, value in enumerate(values):
        x = index * width / last_index
        y = (height - 2) - ((value - low) / span) * (height - 4)
        parts.append(f"{x:.1f},{y:.1f}")
    return " ".join(parts)


def matched_lines(conn: sqlite3.Connection, activity: dict) -> list[dict]:
    keys = [key.casefold() for key in activity.get("keys") or []]
    if not keys:
        return []
    placeholders = ",".join("?" for _ in keys)
    # Match promo codes at order level: CT often stores the code on a separate
    # line without a SKU, while product lines carry the commercial quantities.
    rows = conn.execute(
        f"""
        SELECT order_id, line_id, order_date, sku, product_name, quantity, amount, discount_amount, currency
        FROM order_lines
        WHERE cancelled = 0
          AND order_date >= ?
          AND order_date <= ?
          AND sku IS NOT NULL
          AND TRIM(sku) != ''
          AND EXISTS (
              SELECT 1 FROM order_promos
              WHERE order_promos.order_id = order_lines.order_id
                AND order_promos.promo_key_norm IN ({placeholders})
          )
        """,
        (activity["start_date"], activity["end_date"], *keys),
    ).fetchall()
    return [dict(row) for row in rows]


def baseline_lines(conn: sqlite3.Connection, activity: dict, skus: set[str]) -> list[dict]:
    if not activity.get("baseline_start") or not activity.get("baseline_end"):
        return []
    params: list = [activity["baseline_start"], activity["baseline_end"]]
    sku_sql = ""
    if skus:
        placeholders = ",".join("?" for _ in skus)
        sku_sql = f" AND sku IN ({placeholders})"
        params.extend(sorted(skus))
    rows = conn.execute(
        f"""
        SELECT order_id, line_id, order_date, sku, product_name, quantity, amount, discount_amount, currency
        FROM order_lines
        WHERE cancelled = 0
          AND order_date >= ?
          AND order_date <= ?
          {sku_sql}
        """,
        params,
    ).fetchall()
    return [dict(row) for row in rows]


def shared_product_ids(conn: sqlite3.Connection, activity: dict, others: list[dict]) -> set[int]:
    ours = {line["sku"] for line in matched_lines(conn, activity) if line.get("sku")}
    if not ours:
        return set()
    shared = set()
    for other in others:
        if other["id"] == activity["id"] or other["status"] == "cancelled" or not other.get("keys"):
            continue
        theirs = {line["sku"] for line in matched_lines(conn, other) if line.get("sku")}
        if ours & theirs:
            shared.add(other["id"])
    return shared


def _group_currency(lines: list[dict]) -> dict[str, list[dict]]:
    groups: dict[str, list[dict]] = {}
    for line in lines:
        currency = (line.get("currency") or "").strip().upper() or "—"
        groups.setdefault(currency, []).append(line)
    return groups


def _import_message(latest: dict | None) -> str:
    if not latest:
        return "Results will appear after an order export is imported."
    return f"From {latest['filename']}, imported {format_timestamp(latest['imported_at'])}."


def score_activity(conn: sqlite3.Connection, activity: dict) -> Score:
    latest_row = conn.execute("SELECT * FROM imports ORDER BY id DESC LIMIT 1").fetchone()
    latest = dict(latest_row) if latest_row else None
    keys = list(activity.get("keys") or [])
    if latest is None:
        return Score("no_import", "Results will appear after an order export is imported.")
    if not keys:
        return Score(
            "no_keys",
            "There is no promo code or name on this activity, so orders cannot be matched. It stays on the plan and is not scored.",
        )

    lines = matched_lines(conn, activity)
    found_norms = set()
    norms = [key.casefold() for key in keys]
    placeholders = ",".join("?" for _ in norms)
    order_ids = {line["order_id"] for line in lines}
    if order_ids:
        order_placeholders = ",".join("?" for _ in order_ids)
        promo_rows = conn.execute(
            f"""
            SELECT DISTINCT promo_key_norm FROM order_promos
            WHERE promo_key_norm IN ({placeholders})
              AND order_id IN ({order_placeholders})
            """,
            (*norms, *order_ids),
        ).fetchall()
        found_norms = {row["promo_key_norm"] for row in promo_rows}
    elif norms:
        # Codes may exist on non-SKU lines only — still report if they appear in the window.
        promo_rows = conn.execute(
            f"""
            SELECT DISTINCT order_promos.promo_key_norm
            FROM order_promos
            JOIN order_lines ON order_lines.order_id = order_promos.order_id
            WHERE order_promos.promo_key_norm IN ({placeholders})
              AND order_lines.cancelled = 0
              AND order_lines.order_date >= ?
              AND order_lines.order_date <= ?
            """,
            (*norms, activity["start_date"], activity["end_date"]),
        ).fetchall()
        found_norms = {row["promo_key_norm"] for row in promo_rows}
    keys_found = [key for key in keys if key.casefold() in found_norms]
    keys_missing = [key for key in keys if key.casefold() not in found_norms]
    window = format_range(activity["start_date"], activity["end_date"])
    days = _days(activity["start_date"], activity["end_date"])
    source = _import_message(latest)

    if not lines:
        missing = ", ".join(keys)
        return Score(
            "no_match",
            f"None of the codes ({missing}) appear on orders between {window}. This is not scored as a failed activity.",
            keys_missing=keys,
        )

    skus = {line["sku"] for line in lines if line.get("sku")}
    has_baseline = bool(activity.get("baseline_start") and activity.get("baseline_end"))
    base = baseline_lines(conn, activity, skus) if has_baseline else None
    baseline_days = _days(activity["baseline_start"], activity["baseline_end"]) if has_baseline else None
    notes = []
    if keys_missing:
        notes.append(f"No orders in this window used {', '.join(keys_missing)}.")
    if has_baseline and not skus:
        notes.append("The file has no SKU on the matched rows, so the baseline is every product in that window.")
    if has_baseline and base == []:
        notes.append("The baseline window has no orders for these products.")

    currencies = _group_currency(lines)
    base_currencies = _group_currency(base) if base is not None else {}
    state = "mixed" if len(currencies) > 1 else ("no_baseline" if not has_baseline else "ok")
    figures = []
    for currency in sorted(currencies):
        group_lines = currencies[currency]
        group_base = base_currencies.get(currency, []) if has_baseline else None
        if has_baseline and currency not in base_currencies:
            group_base = []
        figures.append(
            CurrencyFigures(
                currency=currency,
                revenue=_measure(group_lines, "amount", days, group_base, baseline_days),
                orders=_order_measure(group_lines, days, group_base, baseline_days),
                units=_measure(group_lines, "quantity", days, group_base, baseline_days),
                discount=_measure(group_lines, "discount_amount", days, None, None),
                spark_points=_spark(group_lines, activity["start_date"], activity["end_date"]),
            )
        )

    if state == "mixed":
        codes = ", ".join(currency for currency in currencies if currency != "—")
        message = (
            f"{source} Matched orders run {window} ({format_day_count(days)}). "
            f"They use more than one currency ({codes}), so the totals stay separate and are not added together."
        )
    elif state == "no_baseline":
        message = (
            f"{source} Matched orders run {window} ({format_day_count(days)}). "
            "Set a baseline window to compare these totals with another period."
        )
    else:
        baseline_label = format_range(activity["baseline_start"], activity["baseline_end"])
        message = (
            f"{source} Matched orders run {window} ({format_day_count(days)}), "
            f"set against the same products from {baseline_label} ({format_day_count(baseline_days or 0)}). "
            "Totals are also shown per day. This comparison does not show that the activity caused the difference."
        )
    return Score(state, message, notes=notes, figures=figures, keys_found=keys_found, keys_missing=keys_missing)


def format_day_count(days: int) -> str:
    return "1 day" if days == 1 else f"{days} days"


def reading_line(score: Score, name: str | None = None) -> str:
    text = "no order file yet"
    if score.state == "no_keys":
        text = "not scored"
    elif score.state == "no_match":
        text = "codes not found on orders"
    elif score.state == "mixed":
        text = "more than one currency"
    elif score.state == "no_baseline":
        text = "baseline not set"
    elif score.state == "ok" and score.figures:
        ratio = score.figures[0].revenue.delta_ratio
        baseline_total = score.figures[0].revenue.baseline_total
        if ratio is None and baseline_total == 0:
            text = "baseline revenue per day is zero"
        elif ratio is None:
            text = "amount was not in the file"
        else:
            pct = abs(ratio * 100)
            number = f"{pct:.0f}" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}"
            if abs(ratio) < 0.0005:
                text = "revenue per day in line with baseline"
            elif ratio > 0:
                text = f"revenue per day {number}% above baseline"
            else:
                text = f"revenue per day {number}% below baseline"
    elif score.state == "no_import":
        text = "no order file yet"
    if name:
        return f"{name} — {text}"
    return text.capitalize() if text[:1].islower() else text
