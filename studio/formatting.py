from __future__ import annotations

from datetime import date, datetime


def format_date(value: date | str | None) -> str:
    if not value:
        return ""
    if isinstance(value, str):
        value = date.fromisoformat(value[:10])
    return f"{value.day} {value.strftime('%b')} {value.year}"


def format_range(start: date | str, end: date | str) -> str:
    start_d = date.fromisoformat(start[:10]) if isinstance(start, str) else start
    end_d = date.fromisoformat(end[:10]) if isinstance(end, str) else end
    if start_d == end_d:
        return format_date(start_d)
    if start_d.year == end_d.year and start_d.month == end_d.month:
        return f"{start_d.day}–{end_d.day} {start_d.strftime('%b')} {start_d.year}"
    if start_d.year == end_d.year:
        return f"{start_d.day} {start_d.strftime('%b')} – {end_d.day} {end_d.strftime('%b')} {start_d.year}"
    return f"{format_date(start_d)} – {format_date(end_d)}"


def format_money(amount: float | None, currency: str | None = None) -> str:
    if amount is None:
        return "—"
    text = f"{amount:,.2f}"
    if currency and currency != "—":
        return f"{text} {currency}"
    return text


def format_count(amount: float | None) -> str:
    if amount is None:
        return "—"
    rounded = round(amount)
    if abs(amount - rounded) < 0.001:
        return f"{int(rounded):,}"
    return f"{amount:,.2f}"


def format_delta(ratio: float | None) -> str | None:
    if ratio is None:
        return None
    pct = abs(ratio * 100)
    if pct < 0.05:
        return "in line with the baseline"
    number = f"{pct:.0f}" if abs(pct - round(pct)) < 0.05 else f"{pct:.1f}"
    if ratio > 0:
        return f"{number}% above the baseline"
    return f"{number}% below the baseline"


def format_days(count: float) -> str:
    if abs(count - round(count)) < 0.05:
        n = int(round(count))
        return f"{n} day" if n == 1 else f"{n} days"
    return f"{count:.1f} days"


def format_timestamp(value: str) -> str:
    parsed = datetime.fromisoformat(value)
    return f"{parsed.day} {parsed.strftime('%b')} {parsed.year}, {parsed.strftime('%H:%M')}"


def inclusive_days(start: date, end: date) -> int:
    return (end - start).days + 1
