# Studio

A campaign operating desk for an e-shop manager who plans promos without shop API access.

Commercetools stays the system of record for live discounts. Studio is where you:

1. **Plan** activities on a calendar (mechanic, offer, shops, SKUs).
2. **Gate** them with campaign rules (blocked products, gaps, legal checklist).
3. **Brief** other teams with planning packs (Merchant Center setup, stock ask, asset brief, legal).
4. **Read** results after the fact from an order CSV import.

Locally there is no login. On Fly.io, set `STUDIO_USER` / `STUDIO_PASSWORD` so the public URL uses HTTP basic auth. Only put order data on a host your company allows.

## MVP scope

| In MVP | Out of MVP (later) |
|---|---|
| Calendar + activity form | Live CT / SFMC / SAP APIs |
| Campaign rules + warnings | Full SSO / multi-user roles |
| Planning packs (setup, stock, assets, legal) | AI agent |
| Catalog + order CSV import | Profitability without cost data |
| Promo reading vs baseline | Automatic discount creation |
| Fly.io hosting + basic auth | — |

Stock asks use a transparent formula: `units/day × days × uplift`. That is a planning ask, not warehouse truth.

## Run locally

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/studio
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000).

Optional: `STUDIO_HOST=0.0.0.0 STUDIO_PORT=8000` when exposing via a tunnel or Codespace.

## Deploy on Fly.io (browser-only)

You get a HTTPS URL. SQLite lives on a persistent volume at `/data`.

### One-time setup

1. Install the Fly CLI: https://fly.io/docs/flyctl/install/
2. Sign up / log in: `fly auth login`
3. From this repo:

```bash
fly apps create nutriklub-studio   # skip if the app name in fly.toml is free / already yours
fly volumes create studio_data --region arn --size 1
fly secrets set STUDIO_USER='your-login' STUDIO_PASSWORD='choose-a-long-password'
fly deploy
```

4. Open the URL Fly prints (also `fly apps open`).

`fly.toml` keeps one small machine running (`min_machines_running = 1`) so the first page load stays snappy. That uses more of the free allowance than a sleeping app; set `min_machines_running = 0` and `auto_stop_machines = "stop"` if you prefer cheaper cold starts.

### Later deploys

```bash
fly deploy
```

### Useful commands

```bash
fly status
fly logs
fly ssh console
fly volumes list
```

Database file on the volume: `/data/studio.db`.

## Suggested workflow

1. **Settings** — set CT keys, campaign rules (blocked SKUs/categories, min gap), import catalog.
2. **New activity** — objective, mechanic, dates, shops, SKUs, offer.
3. **Planning packs** (sidebar) — copy Setup into Merchant Center, Stock to warehouse, Assets to agency, Legal for yourself.
4. **Mark done** + import orders — read the activity against its baseline.

## Import

Export orders from Commercetools as CSV. Map commercial columns once. Customer names, emails, phones, and street addresses are dropped before storage.

Each import replaces stored orders. `fixtures/orders_sample.csv` is a small stand-in.

## Moving the desk

Copy `data/studio.db` (or `/data/studio.db` from Fly) to another computer. Two copies edited separately will not merge.

## GitHub Codespaces

See `.devcontainer/`. For day-to-day browser use, prefer Fly.io over Codespaces.
