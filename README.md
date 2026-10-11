# Studio

A local planning desk for the shop's marketing, promo, and discount activities. The plan comes first. Order history is evidence you consult after an activity has run.

Commercetools stays the source of truth. Studio keeps a disposable copy in `data/studio.db`.

## Run

```bash
python3 -m venv .venv
.venv/bin/pip install -e ".[dev]"
.venv/bin/studio
```

Open [http://127.0.0.1:8000](http://127.0.0.1:8000). There is no login. The app is meant to stay on your machine.

## Run on GitHub (Codespaces)

GitHub Pages cannot host this app (it needs a Python server and a local SQLite file). Use **Codespaces** instead:

1. Open the repository on GitHub.
2. Click **Code → Codespaces → Create codespace on main**.
3. Wait for the container to finish; Studio starts on port 8000.
4. Open the forwarded port URL (ends with `app.github.dev`).

Do not import real order exports into a shared Codespace unless that is an approved place for that data.

## What a reading means

When an activity is marked done and has a promo code, Studio sums the orders in its dates that carry that code. The baseline is the same products in the baseline dates you set. Both sides are also shown per day, because the two windows are often different lengths.

Cancelled orders are left out when a status column is mapped. Mixed currencies are not added together. A code that never appears on an order is reported as not found. That is not scored as a failure.

The comparison does not show that the activity caused the change. Overlapping activities that share products are named, and the orders are not split between them.

## Import

Export orders from Commercetools as CSV. Map the commercial columns once. Customer names, email addresses, phone numbers, and street addresses are removed before the file is kept, and they are never written into `studio.db`.

Each import replaces the orders already stored. Copy the whole file from Commercetools each time so cancellations and later changes are included. Dates written as `03/04/2026` are read as 3 April 2026.

`fixtures/orders_sample.csv` is a small stand-in for that export. It includes a `WELCOME15` code on 1–14 March 2026 and earlier orders of the same product on 1–4 February. A finished activity with that code and a baseline of 1–14 February should show revenue of 540.00 CZK, 35% above the baseline per day.

## Moving the desk

Copy `data/studio.db` to another computer and start Studio there. Two copies edited separately will not merge.

Do not put that file on a shared or public drive until your company has agreed where this order data may live. There is no account system in this version.
