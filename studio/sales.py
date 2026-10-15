from __future__ import annotations

from datetime import date, timedelta

from studio.formatting import inclusive_days


def sales_window(activity: dict, *, lookback_days: int = 28) -> tuple[str, str] | None:
    if activity.get("baseline_start") and activity.get("baseline_end"):
        return activity["baseline_start"], activity["baseline_end"]
    start_raw = activity.get("start_date") or ""
    if not start_raw:
        return None
    try:
        start = date.fromisoformat(start_raw)
    except ValueError:
        return None
    end = start - timedelta(days=1)
    begin = end - timedelta(days=max(lookback_days, 1) - 1)
    return begin.isoformat(), end.isoformat()


def sku_daily_rates(conn, skus: list[str], window_start: str, window_end: str) -> dict[str, float]:
    if not skus:
        return {}
    try:
        days = inclusive_days(date.fromisoformat(window_start), date.fromisoformat(window_end))
    except ValueError:
        return {}
    if days <= 0:
        return {}
    rates: dict[str, float] = {}
    placeholders = ",".join("?" for _ in skus)
    rows = conn.execute(
        f"""
        SELECT sku, COALESCE(SUM(quantity), 0) AS qty
        FROM order_lines
        WHERE cancelled = 0
          AND sku IN ({placeholders})
          AND order_date >= ?
          AND order_date <= ?
          AND quantity IS NOT NULL
        GROUP BY sku
        """,
        (*skus, window_start, window_end),
    ).fetchall()
    for row in rows:
        qty = float(row["qty"] or 0)
        if qty > 0:
            rates[row["sku"]] = qty / days
    return rates
