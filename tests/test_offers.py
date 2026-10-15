from studio.offers import extract_offer_from_form, offer_to_json, parse_offer_json, sync_legacy_fields


def test_offer_round_trip_and_legacy_sync():
    form = {
        "offer_value_mode": "relative",
        "offer_percent": "20",
        "offer_amount_czk": "",
        "offer_amount_eur": "",
    }
    offer = extract_offer_from_form(form)
    assert offer["percent"] == "20"
    kind, value = sync_legacy_fields("product_discount", offer, form)
    assert kind == "percent"
    assert value == "20%"
    raw = offer_to_json(offer)
    assert parse_offer_json(raw)["percent"] == "20"


def test_activity_type_fields_appear_in_modal(client):
    page = client.get("/?year=2026&activity=new")
    assert page.status_code == 200
    assert 'data-offer-for="product_discount,cart_discount"' in page.text
    assert 'data-offer-for="shipping_discount"' in page.text
    assert 'data-offer-for="multibuy"' in page.text
    assert 'data-offer-for="gift"' in page.text
    assert "Stock planning (per SKU)" in page.text
    assert "Assets to prepare" in page.text
    assert "Homepage banner — CZ" in page.text
