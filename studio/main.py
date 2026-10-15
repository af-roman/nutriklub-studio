from __future__ import annotations

import json
import re
from datetime import date
from typing import List, Optional
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from studio.catalog import (
    apply_catalog_mapping,
    clear_catalog_pending,
    load_catalog_pending,
    load_catalog_pending_rows,
    store_catalog_upload,
)
from studio.constants import (
    ASSET_OPTIONS,
    AUDIENCES,
    CATALOG_FIELDS,
    CODE_REQUIRED,
    DEFAULT_SETTINGS,
    DISCOUNT_KINDS,
    IMPORT_FIELDS,
    SHOP_MODELS,
    SHOP_SHORT,
    SHOPS,
    STATUSES,
    TYPES,
)
from studio.offers import (
    GIFT_MODES,
    MULTIBUY_MODES,
    SHIPPING_MODES,
    VALUE_MODES,
    blank_offer,
    parse_offer_json,
)
from studio.db import (
    catalog_count,
    create_activity,
    delete_activity,
    duplicate_activity,
    get_activity,
    get_catalog_mapping,
    get_mapping,
    get_settings,
    latest_catalog_import,
    latest_import,
    list_activities,
    list_catalog,
    replace_catalog,
    replace_orders,
    save_catalog_mapping,
    save_mapping,
    save_settings,
    session,
    update_activity,
    update_activity_dates,
)
from starlette.middleware.gzip import GZipMiddleware

from studio.auth import BasicAuthMiddleware
from studio.formatting import format_count, format_delta, format_money, format_range, format_timestamp
from studio.forms import FormError, normalize_type, parse_activity_form, parse_keys, parse_schedule
from studio.packs import build_planning_packs
from studio.sales import sales_window, sku_daily_rates
from studio.importer import (
    ImportProblem,
    apply_mapping,
    clear_pending,
    header_is_pii,
    load_pending,
    load_pending_rows,
    store_upload,
)
from studio.planning import (
    date_overlaps,
    filter_activities,
    month_rows,
    next_activity,
    runs_on_shop,
    same_storefront,
    similar_activities,
    year_summary,
    year_timeline,
)
from studio.scoring import reading_line, score_activity, shared_product_ids

PACKAGE = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE / "templates")
templates.env.filters["money"] = format_money
templates.env.filters["count"] = format_count
templates.env.filters["delta"] = format_delta
templates.env.filters["tojson"] = lambda value: json.dumps(value, ensure_ascii=False)
templates.env.globals["STATUSES"] = STATUSES
templates.env.globals["TYPES"] = TYPES
templates.env.globals["SHOPS"] = SHOPS
templates.env.globals["SHOP_SHORT"] = SHOP_SHORT
templates.env.globals["DISCOUNT_KINDS"] = DISCOUNT_KINDS
templates.env.globals["AUDIENCES"] = AUDIENCES
templates.env.globals["CODE_REQUIRED"] = CODE_REQUIRED
templates.env.globals["SHOP_MODELS"] = SHOP_MODELS
templates.env.globals["ASSET_OPTIONS"] = ASSET_OPTIONS
templates.env.globals["VALUE_MODES"] = VALUE_MODES
templates.env.globals["SHIPPING_MODES"] = SHIPPING_MODES
templates.env.globals["MULTIBUY_MODES"] = MULTIBUY_MODES
templates.env.globals["GIFT_MODES"] = GIFT_MODES

app = FastAPI(title="Studio")
app.add_middleware(GZipMiddleware, minimum_size=500)
app.add_middleware(BasicAuthMiddleware)
app.mount("/static", StaticFiles(directory=PACKAGE / "static"), name="static")


@app.middleware("http")
async def cache_static(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/static/"):
        response.headers["Cache-Control"] = "public, max-age=86400"
    return response


@app.get("/healthz")
def healthz():
    return {"ok": True}


def chosen_year(raw, today: date) -> int:
    try:
        year = int(raw)
    except (TypeError, ValueError):
        return today.year
    if 2000 <= year <= 2100:
        return year
    return today.year


def decorate(activities: list[dict]) -> list[dict]:
    for activity in activities:
        activity_type = normalize_type(activity.get("activity_type") or "")
        activity["activity_type"] = activity_type if activity_type in TYPES else "product_discount"
        activity["type_label"] = TYPES[activity["activity_type"]]
        activity["status_label"] = STATUSES[activity["status"]]
        shops = activity.get("shops") or "both"
        activity["shops"] = shops
        activity["shop_label"] = SHOP_SHORT.get(shops, SHOP_SHORT["both"])
        activity["discount_kind"] = activity.get("discount_kind") or ""
        activity["discount_value"] = activity.get("discount_value") or ""
        activity["product_scope"] = activity.get("product_scope") or ""
        activity["code_required"] = activity.get("code_required") or ""
        activity["audience"] = activity.get("audience") or "all"
        activity["discount_kind_label"] = DISCOUNT_KINDS.get(activity["discount_kind"], DISCOUNT_KINDS[""])
        activity["audience_label"] = AUDIENCES.get(activity["audience"], AUDIENCES["all"])
        activity["code_required_label"] = CODE_REQUIRED.get(activity["code_required"], CODE_REQUIRED[""])
    return activities


def plan_path(year: int, view: str = "calendar", shop: str = "all", activity=None) -> str:
    parts = [f"year={year}"]
    if view and view != "calendar":
        parts.append(f"view={view}")
    if shop and shop != "all":
        parts.append(f"shop={shop}")
    if activity is not None:
        parts.append(f"activity={activity}")
    return "/?" + "&".join(parts)


def normalize_view(view: str) -> str:
    if view in {"calendar", "months", "list"}:
        return view
    return "calendar"


def normalize_shop(shop: str) -> str:
    if shop in {"all", "cz", "sk"}:
        return shop
    return "all"


def link_bars(bars_source, year: int, view: str, shop: str) -> None:
    if not bars_source:
        return
    rows = bars_source.get("rows") if isinstance(bars_source, dict) else bars_source
    if isinstance(bars_source, dict):
        for row in rows or []:
            for lane in row.get("lanes") or []:
                for bar in lane:
                    bar["href"] = plan_path(year, view, shop, bar["id"])
    else:
        for month in bars_source:
            for lane in month.get("lanes") or []:
                for bar in lane:
                    bar["href"] = plan_path(year, view, shop, bar["id"])


def render(request: Request, name: str, conn, **ctx):
    today = date.today()
    year = ctx.get("year", today.year)
    latest = latest_import(conn)
    if latest:
        latest["display"] = format_timestamp(latest["imported_at"])
    ctx.setdefault("view", "calendar")
    ctx.setdefault("shop", "all")
    ctx.setdefault("modal", None)
    ctx.setdefault("close_href", plan_path(year, ctx["view"], ctx["shop"]))
    ctx.setdefault("new_activity_href", plan_path(year, ctx["view"], ctx["shop"], "new"))
    ctx.update(request=request, year=year, today_year=today.year, latest_import=latest, today=today)
    return templates.TemplateResponse(request, name, ctx)


def form_from_activity(activity: dict) -> dict:
    offer = parse_offer_json(activity.get("offer_json"))
    asset_keys = [key for key in (activity.get("asset_options") or "").split(",") if key.strip()]
    return {
        "name": activity["name"],
        "activity_type": activity["activity_type"],
        "status": activity["status"],
        "start_date": activity["start_date"],
        "end_date": activity["end_date"],
        "notes": activity["notes"],
        "baseline_start": activity["baseline_start"] or "",
        "baseline_end": activity["baseline_end"] or "",
        "match_keys": "\n".join(activity["keys"]),
        "shops": activity.get("shops") or "both",
        "discount_kind": activity.get("discount_kind") or "",
        "discount_value": activity.get("discount_value") or "",
        "product_scope": activity.get("product_scope") or "",
        "code_required": activity.get("code_required") or "",
        "audience": activity.get("audience") or "all",
        "scope_skus": list(activity.get("skus") or []),
        "sku_lines": list(activity.get("sku_lines") or []),
        "objective": activity.get("objective") or "",
        "stock_units_per_day": activity.get("stock_units_per_day") or "",
        "stock_uplift": activity.get("stock_uplift") or "",
        "asset_notes": activity.get("asset_notes") or "",
        "offer": offer,
        "asset_option_keys": asset_keys,
    }


def blank_form() -> dict:
    return {
        "name": "",
        "activity_type": "product_discount",
        "status": "draft",
        "start_date": "",
        "end_date": "",
        "notes": "",
        "baseline_start": "",
        "baseline_end": "",
        "match_keys": "",
        "shops": "both",
        "discount_kind": "",
        "discount_value": "",
        "product_scope": "",
        "code_required": "",
        "audience": "all",
        "scope_skus": [],
        "sku_lines": [],
        "objective": "",
        "stock_units_per_day": "",
        "stock_uplift": "",
        "asset_notes": "",
        "offer": blank_offer(),
        "asset_option_keys": [],
    }


def _activity_products(conn, form: dict) -> list[dict]:
    selected = list(form.get("scope_skus") or [])
    if not selected and form.get("sku_lines"):
        selected = [line.get("sku") for line in form["sku_lines"] if line.get("sku")]
    if not selected:
        return []
    shops = form.get("shops") or "both"
    shop_filter = None if shops == "both" else shops
    by_sku = {item["sku"].casefold(): item for item in list_catalog(conn, shop=shop_filter)}
    products = []
    seen: set[str] = set()
    for sku in selected:
        key = (sku or "").casefold()
        if not key or key in seen or key not in by_sku:
            continue
        seen.add(key)
        products.append(by_sku[key])
    return products


def _modal_packs(conn, form: dict, activity_id: int | None = None) -> dict:
    settings = get_settings(conn)
    products = _activity_products(conn, form)
    payload = dict(form)
    if activity_id is not None:
        payload["id"] = activity_id
    payload["keys"] = parse_keys(form.get("match_keys") or "")
    payload["sku_lines"] = list(form.get("sku_lines") or [])
    if not payload["sku_lines"] and form.get("scope_skus"):
        payload["sku_lines"] = [
            {"sku": sku, "units_per_day": "", "uplift": "", "ask_override": ""}
            for sku in form["scope_skus"]
        ]
    payload["skus"] = [line["sku"] for line in payload["sku_lines"]]
    payload["offer_json"] = form.get("offer_json") or ""
    if form.get("offer") and not payload["offer_json"]:
        from studio.offers import offer_to_json

        payload["offer"] = form["offer"]
        payload["offer_json"] = offer_to_json(form["offer"])
    payload["asset_options"] = ",".join(form.get("asset_option_keys") or [])
    window = sales_window(payload)
    payload["sales_window"] = window
    if window and payload["skus"]:
        payload["sales_rates"] = sku_daily_rates(conn, payload["skus"], window[0], window[1])
    else:
        payload["sales_rates"] = {}
    others = decorate(list_activities(conn))
    return build_planning_packs(payload, settings, products, others)


def group_by_month(activities: list[dict], year: int) -> list[dict]:
    buckets = {month: [] for month in range(1, 13)}
    for activity in activities:
        start = date.fromisoformat(activity["start_date"])
        if start.year < year:
            month = 1
        elif start.year > year:
            month = 12
        else:
            month = start.month
        buckets[month].append(activity)
    groups = []
    for month, items in buckets.items():
        if not items:
            continue
        groups.append(
            {
                "label": date(year, month, 1).strftime("%B %Y"),
                "count": len(items),
                "items": items,
            }
        )
    return groups


def overlap_view(conn, activity: dict, others: list[dict], year: int, view: str, shop: str) -> list[dict]:
    overlaps = date_overlaps(activity, others)
    shared = set()
    if activity["keys"] and latest_import(conn):
        shared = shared_product_ids(conn, activity, overlaps)
    found = []
    for other in overlaps:
        found.append(
            {
                "name": other["name"],
                "href": plan_path(year, view, shop, other["id"]),
                "dates": format_range(other["start_date"], other["end_date"]),
                "shares_products": other["id"] in shared,
                "shop_label": other.get("shop_label") or SHOP_SHORT.get(other.get("shops") or "both", "CZ · SK"),
                "different_shop": not same_storefront(activity, other),
            }
        )
    return found


def similar_view(conn, activity: dict, others: list[dict], year: int, view: str, shop: str) -> list[dict]:
    found = []
    for item in similar_activities(activity, others):
        if item["status"] == "done":
            reading = reading_line(score_activity(conn, item))
        else:
            reading = f"{STATUSES[item['status']]} · {format_range(item['start_date'], item['end_date'])}"
        found.append(
            {
                "name": item["name"],
                "href": plan_path(year, view, shop, item["id"]),
                "dates": format_range(item["start_date"], item["end_date"]),
                "reading": reading,
            }
        )
    return found


def _catalog_categories(catalog: list[dict]) -> list[str]:
    found: set[str] = set()
    for item in catalog:
        raw = item.get("categories") or ""
        for part in re.split(r"[;|,]", raw):
            token = part.strip()
            if token:
                found.add(token)
    return sorted(found, key=str.casefold)


def _enrich_form_stock(form: dict, packs: dict) -> None:
    stock_lines = {line["sku"]: line for line in (packs.get("stock") or {}).get("lines") or []}
    rates = packs.get("sales_rates") or {}
    for line in form.get("sku_lines") or []:
        sku = line.get("sku") or ""
        info = stock_lines.get(sku) or {}
        if "past_rate" not in line or line.get("past_rate") is None:
            line["past_rate"] = info.get("past_rate", rates.get(sku))
        if "est_ask" not in line:
            line["est_ask"] = info.get("ask")


def build_modal(conn, token: str | None, year: int, view: str, shop: str, form=None, error: str = ""):
    if not token:
        return None
    others = decorate(list_activities(conn))
    catalog = list_catalog(conn)
    settings = get_settings(conn)
    default_uplift = (settings.get("default_stock_uplift") or "1.3").strip() or "1.3"
    categories = _catalog_categories(catalog)
    if token == "new":
        form = form or blank_form()
        packs = _modal_packs(conn, form)
        _enrich_form_stock(form, packs)
        return {
            "form": form,
            "error": error,
            "activity": None,
            "score": None,
            "overlaps": [],
            "similar": [],
            "catalog": catalog,
            "catalog_categories": categories,
            "packs": packs,
            "checklist": packs["checklist"],
            "sales_rates": packs.get("sales_rates") or {},
            "default_uplift": default_uplift,
        }
    try:
        activity_id = int(token)
    except (TypeError, ValueError):
        return None
    activity = get_activity(conn, activity_id)
    if activity is None:
        return None
    decorate([activity])
    overlaps = overlap_view(conn, activity, others, year, view, shop)
    similar = similar_view(conn, activity, others, year, view, shop)
    score = score_activity(conn, activity) if activity["status"] == "done" else None
    form = form or form_from_activity(activity)
    packs = _modal_packs(conn, form, activity_id=activity["id"])
    _enrich_form_stock(form, packs)
    return {
        "form": form,
        "error": error,
        "activity": activity,
        "score": score,
        "overlaps": overlaps,
        "similar": similar,
        "catalog": catalog,
        "catalog_categories": categories,
        "packs": packs,
        "checklist": packs["checklist"],
        "sales_rates": packs.get("sales_rates") or {},
        "default_uplift": default_uplift,
    }


def render_plan(
    request: Request,
    conn,
    *,
    year: int,
    view: str,
    shop: str,
    status: str = "all",
    when: str = "all",
    activity_type: str = "all",
    q: str = "",
    modal_token: str | None = None,
    form=None,
    error: str = "",
):
    today = date.today()
    view = normalize_view(view)
    shop = normalize_shop(shop)
    if status not in {"all", *STATUSES}:
        status = "all"
    if when not in {"all", "upcoming", "past"}:
        when = "all"
    if activity_type not in {"all", *TYPES}:
        activity_type = "all"
    activities = [item for item in decorate(list_activities(conn, year)) if runs_on_shop(item, shop)]
    summary = year_summary(activities, year)
    upcoming = next_activity(activities, today) if summary else None
    if upcoming:
        upcoming["href"] = plan_path(year, view, shop, upcoming["id"])
    done = sorted((item for item in activities if item["status"] == "done"), key=lambda item: item["end_date"], reverse=True)
    scored = [(item, score_activity(conn, item)) for item in done]
    useful = [
        pair
        for pair in scored
        if pair[1].state == "ok" and pair[1].figures and pair[1].figures[0].revenue.delta_ratio is not None
    ]
    readings = [
        {
            "href": plan_path(year, view, shop, item["id"]),
            "reading": reading_line(result, item["name"]),
        }
        for item, result in (useful or scored)[:2]
    ]
    counts = {name: sum(1 for item in activities if item["status"] == name) for name in STATUSES}
    filtered = filter_activities(activities, status, when, activity_type, q, today)
    for item in filtered:
        item["dates"] = format_range(item["start_date"], item["end_date"])
        item["reading"] = reading_line(score_activity(conn, item)) if item["status"] == "done" else ""
        item["href"] = plan_path(year, view, shop, item["id"])
    timeline = year_timeline(activities, year, today) if view == "calendar" else None
    months = month_rows(activities, year, today) if view == "months" else []
    link_bars(timeline, year, view, shop)
    link_bars(months, year, view, shop)
    modal = build_modal(conn, modal_token, year, view, shop, form=form, error=error)
    title = "Ledger" if view == "list" else "Plan"
    if modal and modal["form"]["name"]:
        title = modal["form"]["name"]
    elif modal:
        title = "New activity"
    return render(
        request,
        "list.html" if view == "list" else "plan.html",
        conn,
        nav=view,
        title=title,
        year=year,
        view=view,
        shop=shop,
        timeline=timeline,
        months=months,
        summary=summary,
        upcoming=upcoming,
        readings=readings,
        open_year=summary is None,
        activities=filtered,
        groups=group_by_month(filtered, year),
        counts=counts,
        status=status,
        when=when,
        activity_type=activity_type,
        query=q,
        modal=modal,
        close_href=plan_path(year, view, shop),
        new_activity_href=plan_path(year, view, shop, "new"),
    )


@app.get("/")
def home(
    request: Request,
    year: Optional[str] = None,
    view: str = "calendar",
    status: str = "all",
    when: str = "all",
    activity_type: str = "all",
    shop: str = "all",
    activity: Optional[str] = None,
    q: str = "",
):
    selected = chosen_year(year, date.today())
    with session() as conn:
        return render_plan(
            request,
            conn,
            year=selected,
            view=view,
            shop=shop,
            status=status,
            when=when,
            activity_type=activity_type,
            q=q,
            modal_token=activity,
        )


def _save(conn, form: dict, activity_id: int | None) -> int:
    fields, keys, skus = parse_activity_form(form)
    if activity_id is None:
        return create_activity(conn, fields, keys, skus)
    update_activity(conn, activity_id, fields, keys, skus)
    return activity_id


def _multi(form_data, key: str) -> list[str]:
    return [str(value) for value in form_data.getlist(key)]


def _one(form_data, key: str, default: str = "") -> str:
    value = form_data.get(key)
    if value is None:
        return default
    return str(value)


async def _activity_form_from_http(request: Request) -> tuple[dict, str, str, str]:
    form_data = await request.form()
    offer = blank_offer()
    for key in offer:
        offer[key] = _one(form_data, f"offer_{key}")
    form = {
        "name": _one(form_data, "name"),
        "activity_type": _one(form_data, "activity_type"),
        "status": _one(form_data, "status", "draft"),
        "start_date": _one(form_data, "start_date"),
        "end_date": _one(form_data, "end_date"),
        "notes": _one(form_data, "notes"),
        "baseline_start": _one(form_data, "baseline_start"),
        "baseline_end": _one(form_data, "baseline_end"),
        "match_keys": _one(form_data, "match_keys"),
        "shops": _one(form_data, "shops", "both"),
        "product_scope": _one(form_data, "product_scope"),
        "code_required": _one(form_data, "code_required"),
        "audience": _one(form_data, "audience", "all"),
        "scope_skus": _multi(form_data, "scope_sku"),
        "stock_sku": _multi(form_data, "stock_sku"),
        "stock_units": _multi(form_data, "stock_units"),
        "stock_uplift_line": _multi(form_data, "stock_uplift_line"),
        "stock_ask": _multi(form_data, "stock_ask"),
        "objective": _one(form_data, "objective"),
        "asset_notes": _one(form_data, "asset_notes"),
        "asset_option": _multi(form_data, "asset_option"),
        "offer": offer,
    }
    for key, value in offer.items():
        form[f"offer_{key}"] = value
    year = _one(form_data, "year")
    return_view = _one(form_data, "return_view", "calendar")
    return_shop = _one(form_data, "return_shop", "all")
    return form, year, return_view, return_shop


def _form_for_redisplay(form: dict) -> dict:
    """Shape submitted form data for the modal after a validation error."""
    offer = form.get("offer") or extract_offer_helper(form)
    sku_lines = []
    units = form.get("stock_units") or []
    uplifts = form.get("stock_uplift_line") or []
    asks = form.get("stock_ask") or []
    for index, sku in enumerate(form.get("stock_sku") or form.get("scope_skus") or []):
        sku_lines.append(
            {
                "sku": sku,
                "units_per_day": units[index] if index < len(units) else "",
                "uplift": uplifts[index] if index < len(uplifts) else "",
                "ask_override": asks[index] if index < len(asks) else "",
            }
        )
    if not sku_lines:
        for sku in form.get("scope_skus") or []:
            sku_lines.append({"sku": sku, "units_per_day": "", "uplift": "", "ask_override": ""})
    return {
        **form,
        "offer": offer,
        "sku_lines": sku_lines,
        "scope_skus": form.get("scope_skus") or [line["sku"] for line in sku_lines],
        "asset_option_keys": form.get("asset_option") or form.get("asset_option_keys") or [],
    }


def extract_offer_helper(form: dict) -> dict:
    from studio.offers import extract_offer_from_form

    return extract_offer_from_form(form)


@app.post("/activities")
async def create_activity_route(request: Request):
    form, year, return_view, return_shop = await _activity_form_from_http(request)
    selected = chosen_year(year, date.today())
    view = normalize_view(return_view)
    shop = normalize_shop(return_shop)
    with session() as conn:
        try:
            activity_id = _save(conn, form, None)
        except FormError as exc:
            return render_plan(
                request,
                conn,
                year=selected,
                view=view,
                shop=shop,
                modal_token="new",
                form=_form_for_redisplay(form),
                error=exc.message,
            )
        return RedirectResponse(plan_path(selected, view, shop, activity_id), status_code=303)


@app.get("/activities/new")
def new_activity(request: Request, year: Optional[str] = None, view: str = "calendar", shop: str = "all"):
    selected = chosen_year(year, date.today())
    return RedirectResponse(plan_path(selected, normalize_view(view), normalize_shop(shop), "new"), status_code=303)


@app.get("/activities/{activity_id}")
def show_activity(request: Request, activity_id: int, view: str = "calendar", shop: str = "all"):
    with session() as conn:
        activity = get_activity(conn, activity_id)
        if activity is None:
            raise HTTPException(status_code=404)
        year = date.fromisoformat(activity["start_date"]).year
        return RedirectResponse(
            plan_path(year, normalize_view(view), normalize_shop(shop), activity_id),
            status_code=303,
        )


@app.post("/activities/{activity_id}/schedule")
def schedule_activity_route(
    activity_id: int,
    start_date: str = Form(""),
    end_date: str = Form(""),
):
    with session() as conn:
        try:
            start, end = parse_schedule(start_date, end_date)
        except FormError as exc:
            return JSONResponse({"ok": False, "error": exc.message}, status_code=400)
        activity = update_activity_dates(conn, activity_id, start, end)
        if activity is None:
            raise HTTPException(status_code=404)
        return {
            "ok": True,
            "id": activity_id,
            "start_date": start,
            "end_date": end,
            "dates": format_range(start, end),
        }


@app.post("/activities/{activity_id}")
async def save_activity_route(request: Request, activity_id: int):
    form, year, return_view, return_shop = await _activity_form_from_http(request)
    view = normalize_view(return_view)
    shop = normalize_shop(return_shop)
    with session() as conn:
        existing = get_activity(conn, activity_id)
        if existing is None:
            raise HTTPException(status_code=404)
        selected = chosen_year(year, date.fromisoformat(existing["start_date"]))
        try:
            _save(conn, form, activity_id)
        except FormError as exc:
            return render_plan(
                request,
                conn,
                year=selected,
                view=view,
                shop=shop,
                modal_token=str(activity_id),
                form=_form_for_redisplay(form),
                error=exc.message,
            )
        return RedirectResponse(plan_path(selected, view, shop, activity_id), status_code=303)


@app.post("/activities/{activity_id}/duplicate")
def duplicate_route(
    activity_id: int,
    return_view: str = Form("calendar"),
    return_shop: str = Form("all"),
):
    with session() as conn:
        source = get_activity(conn, activity_id)
        new_id = duplicate_activity(conn, activity_id)
        if new_id is None or source is None:
            raise HTTPException(status_code=404)
        year = date.fromisoformat(source["start_date"]).year
        return RedirectResponse(
            plan_path(year, normalize_view(return_view), normalize_shop(return_shop), new_id),
            status_code=303,
        )


@app.post("/activities/{activity_id}/delete")
def delete_route(
    activity_id: int,
    return_view: str = Form("calendar"),
    return_shop: str = Form("all"),
):
    with session() as conn:
        activity = get_activity(conn, activity_id)
        if activity is None:
            raise HTTPException(status_code=404)
        year = date.fromisoformat(activity["start_date"]).year
        delete_activity(conn, activity_id)
        return RedirectResponse(
            plan_path(year, normalize_view(return_view), normalize_shop(return_shop)),
            status_code=303,
        )


@app.get("/settings")
def settings_page(request: Request, saved: int = 0, catalog_done: int = 0):
    with session() as conn:
        pending = _catalog_pending_with_saved_map(conn)
        latest = latest_catalog_import(conn)
        if latest:
            latest["display"] = format_timestamp(latest["imported_at"])
        products = list_catalog(conn)
        return render(
            request,
            "settings.html",
            conn,
            nav="settings",
            title="Settings",
            settings=get_settings(conn),
            catalog_pending=pending,
            catalog_fields=CATALOG_FIELDS,
            catalog_count=catalog_count(conn),
            catalog_products=products[:80],
            latest_catalog=latest,
            saved=bool(saved),
            catalog_done=bool(catalog_done),
            error="",
        )


@app.post("/settings")
def save_settings_route(
    shop_model: str = Form("stores"),
    cz_key: str = Form(""),
    sk_key: str = Form(""),
    locale_cz: str = Form(""),
    locale_sk: str = Form(""),
    currency_cz: str = Form(""),
    currency_sk: str = Form(""),
    predicate_style: str = Form("sku"),
    registered_customer_group_key: str = Form(""),
    key_pattern_cart: str = Form(""),
    key_pattern_code: str = Form(""),
    key_pattern_product: str = Form(""),
    default_sort_order: str = Form(""),
    notes: str = Form(""),
    blocked_skus: str = Form(""),
    blocked_categories: str = Form(""),
    min_gap_days: str = Form("7"),
    legal_checklist: str = Form(""),
    stacking_notes: str = Form(""),
    default_stock_uplift: str = Form(""),
):
    if shop_model not in SHOP_MODELS:
        shop_model = "stores"
    if predicate_style not in {"sku", "product_key"}:
        predicate_style = "sku"
    gap = (min_gap_days or "").strip() or DEFAULT_SETTINGS["min_gap_days"]
    try:
        gap_n = max(0, int(float(gap)))
        gap = str(gap_n)
    except ValueError:
        gap = DEFAULT_SETTINGS["min_gap_days"]
    uplift = (default_stock_uplift or "").strip() or DEFAULT_SETTINGS["default_stock_uplift"]
    try:
        if float(uplift.replace(",", ".")) < 0:
            uplift = DEFAULT_SETTINGS["default_stock_uplift"]
    except ValueError:
        uplift = DEFAULT_SETTINGS["default_stock_uplift"]
    values = {
        "shop_model": shop_model,
        "cz_key": cz_key.strip()[:120],
        "sk_key": sk_key.strip()[:120],
        "locale_cz": (locale_cz.strip() or DEFAULT_SETTINGS["locale_cz"])[:20],
        "locale_sk": (locale_sk.strip() or DEFAULT_SETTINGS["locale_sk"])[:20],
        "currency_cz": (currency_cz.strip() or DEFAULT_SETTINGS["currency_cz"])[:8].upper(),
        "currency_sk": (currency_sk.strip() or DEFAULT_SETTINGS["currency_sk"])[:8].upper(),
        "predicate_style": predicate_style,
        "registered_customer_group_key": registered_customer_group_key.strip()[:120],
        "key_pattern_cart": (key_pattern_cart.strip() or DEFAULT_SETTINGS["key_pattern_cart"])[:120],
        "key_pattern_code": (key_pattern_code.strip() or DEFAULT_SETTINGS["key_pattern_code"])[:120],
        "key_pattern_product": (key_pattern_product.strip() or DEFAULT_SETTINGS["key_pattern_product"])[:120],
        "default_sort_order": (default_sort_order.strip() or DEFAULT_SETTINGS["default_sort_order"])[:20],
        "notes": notes.strip()[:2000],
        "blocked_skus": blocked_skus.strip()[:5000],
        "blocked_categories": blocked_categories.strip()[:5000],
        "min_gap_days": gap[:20],
        "legal_checklist": legal_checklist.strip()[:5000],
        "stacking_notes": stacking_notes.strip()[:2000],
        "default_stock_uplift": uplift[:40],
    }
    with session() as conn:
        save_settings(conn, values)
    return RedirectResponse("/settings?saved=1", status_code=303)


def _catalog_pending_with_saved_map(conn):
    pending = load_catalog_pending()
    if not pending:
        return None
    suggested = dict(pending.get("suggested") or {})
    for field, header in get_catalog_mapping(conn).items():
        if header in pending["headers"]:
            suggested[field] = header
    pending["suggested"] = suggested
    return pending


@app.post("/settings/catalog/upload")
def upload_catalog(request: Request, file: UploadFile = File(...)):
    raw = file.file.read()
    with session() as conn:
        if not raw:
            return render(
                request,
                "settings.html",
                conn,
                nav="settings",
                title="Settings",
                settings=get_settings(conn),
                catalog_pending=None,
                catalog_fields=CATALOG_FIELDS,
                catalog_count=catalog_count(conn),
                catalog_products=list_catalog(conn)[:80],
                latest_catalog=latest_catalog_import(conn),
                saved=False,
                catalog_done=False,
                error="Choose a CSV file.",
            )
        try:
            store_catalog_upload(file.filename or "catalog.csv", raw)
        except ImportProblem as exc:
            return render(
                request,
                "settings.html",
                conn,
                nav="settings",
                title="Settings",
                settings=get_settings(conn),
                catalog_pending=None,
                catalog_fields=CATALOG_FIELDS,
                catalog_count=catalog_count(conn),
                catalog_products=list_catalog(conn)[:80],
                latest_catalog=latest_catalog_import(conn),
                saved=False,
                catalog_done=False,
                error=exc.message,
            )
        return RedirectResponse("/settings", status_code=303)


@app.post("/settings/catalog/commit")
def commit_catalog(
    request: Request,
    map_sku: str = Form(""),
    map_product_key: str = Form(""),
    map_variant_key: str = Form(""),
    map_name: str = Form(""),
    map_categories: str = Form(""),
    map_shops: str = Form(""),
):
    mapping = {
        "sku": map_sku.strip(),
        "product_key": map_product_key.strip(),
        "variant_key": map_variant_key.strip(),
        "name": map_name.strip(),
        "categories": map_categories.strip(),
        "shops": map_shops.strip(),
    }
    with session() as conn:
        pending = _catalog_pending_with_saved_map(conn)
        error = ""
        if pending is None:
            error = "Load a file before storing the catalog."
        elif not mapping["sku"]:
            error = "Map a SKU column."
        elif any(header and header_is_pii(header) for header in mapping.values()):
            error = "A mapped column looks like a customer detail. Studio will not store it."
        if error:
            latest = latest_catalog_import(conn)
            if latest:
                latest["display"] = format_timestamp(latest["imported_at"])
            return render(
                request,
                "settings.html",
                conn,
                nav="settings",
                title="Settings",
                settings=get_settings(conn),
                catalog_pending=pending,
                catalog_fields=CATALOG_FIELDS,
                catalog_count=catalog_count(conn),
                catalog_products=list_catalog(conn)[:80],
                latest_catalog=latest,
                saved=False,
                catalog_done=False,
                error=error,
                posted_mapping=mapping,
            )
        rows, skipped = apply_catalog_mapping(load_catalog_pending_rows(), mapping)
        if not rows:
            latest = latest_catalog_import(conn)
            if latest:
                latest["display"] = format_timestamp(latest["imported_at"])
            return render(
                request,
                "settings.html",
                conn,
                nav="settings",
                title="Settings",
                settings=get_settings(conn),
                catalog_pending=pending,
                catalog_fields=CATALOG_FIELDS,
                catalog_count=catalog_count(conn),
                catalog_products=list_catalog(conn)[:80],
                latest_catalog=latest,
                saved=False,
                catalog_done=False,
                error="No products could be read. Check the SKU column.",
                posted_mapping=mapping,
            )
        replace_catalog(conn, rows, {"filename": pending["filename"]})
        save_catalog_mapping(conn, mapping)
    clear_catalog_pending()
    return RedirectResponse("/settings?catalog_done=1", status_code=303)


@app.post("/settings/catalog/discard")
def discard_catalog():
    clear_catalog_pending()
    return RedirectResponse("/settings", status_code=303)


@app.get("/import")
def import_page(request: Request, done: int = 0):
    with session() as conn:
        pending = _pending_with_saved_map(conn)
        return render(
            request,
            "import.html",
            conn,
            nav="import",
            title="Import orders",
            pending=pending,
            fields=IMPORT_FIELDS,
            just_imported=bool(done),
            error="",
        )


def _pending_with_saved_map(conn):
    pending = load_pending()
    if not pending:
        return None
    suggested = dict(pending.get("suggested") or {})
    for field, header in get_mapping(conn).items():
        if header in pending["headers"]:
            suggested[field] = header
    pending["suggested"] = suggested
    return pending


@app.post("/import/upload")
def upload_orders(request: Request, file: UploadFile = File(...)):
    raw = file.file.read()
    with session() as conn:
        if not raw:
            return render(
                request,
                "import.html",
                conn,
                nav="import",
                title="Import orders",
                pending=None,
                fields=IMPORT_FIELDS,
                just_imported=False,
                error="Choose a CSV file.",
            )
        try:
            store_upload(file.filename or "orders.csv", raw)
        except ImportProblem as exc:
            return render(
                request,
                "import.html",
                conn,
                nav="import",
                title="Import orders",
                pending=None,
                fields=IMPORT_FIELDS,
                just_imported=False,
                error=exc.message,
            )
        return RedirectResponse("/import", status_code=303)


@app.post("/import/commit")
def commit_import(
    request: Request,
    map_order_id: str = Form(""),
    map_line_id: str = Form(""),
    map_order_date: str = Form(""),
    map_status: str = Form(""),
    map_sku: str = Form(""),
    map_product_name: str = Form(""),
    map_quantity: str = Form(""),
    map_amount: str = Form(""),
    map_discount_amount: str = Form(""),
    map_currency: str = Form(""),
    map_promo_key: str = Form(""),
    amounts_in_cents: str = Form(""),
):
    mapping = {
        "order_id": map_order_id.strip(),
        "line_id": map_line_id.strip(),
        "order_date": map_order_date.strip(),
        "status": map_status.strip(),
        "sku": map_sku.strip(),
        "product_name": map_product_name.strip(),
        "quantity": map_quantity.strip(),
        "amount": map_amount.strip(),
        "discount_amount": map_discount_amount.strip(),
        "currency": map_currency.strip(),
        "promo_key": map_promo_key.strip(),
    }
    in_cents = amounts_in_cents.strip().lower() in {"1", "on", "yes", "true"}
    with session() as conn:
        pending = _pending_with_saved_map(conn)
        error = ""
        if pending is None:
            error = "Load a file before storing orders."
        elif not mapping["order_id"] or not mapping["order_date"]:
            error = "Map an order ID and an order date."
        elif any(header and header_is_pii(header) for header in mapping.values()):
            error = "A mapped column looks like a customer detail. Studio will not store it."
        if error:
            return render(
                request,
                "import.html",
                conn,
                nav="import",
                title="Import orders",
                pending=pending,
                fields=IMPORT_FIELDS,
                just_imported=False,
                error=error,
                posted_mapping=mapping,
            )
        rows, skipped = apply_mapping(load_pending_rows(), mapping, amounts_in_cents=in_cents)
        if not rows:
            return render(
                request,
                "import.html",
                conn,
                nav="import",
                title="Import orders",
                pending=pending,
                fields=IMPORT_FIELDS,
                just_imported=False,
                error="No orders could be read. Check the order ID and date columns.",
                posted_mapping=mapping,
            )
        replace_orders(
            conn,
            rows,
            {
                "filename": pending["filename"],
                "row_count": pending["row_count"],
                "grain": "line" if any(row["line_id"] for row in rows) else "order",
                "has_quantity": any(row["quantity"] is not None for row in rows),
                "has_amount": any(row["amount"] is not None for row in rows),
                "has_discount": any(row["discount_amount"] is not None for row in rows),
                "skipped_rows": skipped,
            },
        )
        save_mapping(conn, mapping)
    clear_pending()
    return RedirectResponse("/import?done=1", status_code=303)


@app.post("/import/discard")
def discard_import():
    clear_pending()
    return RedirectResponse("/import", status_code=303)


@app.exception_handler(HTTPException)
async def http_error(request: Request, exc: HTTPException):
    if exc.status_code != 404:
        return JSONResponse({"detail": exc.detail}, status_code=exc.status_code)
    with session() as conn:
        return render(request, "not_found.html", conn, nav="", title="Not found")
