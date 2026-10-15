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
    assert "Cart predicate builder" in page.text
    assert "Stop stacking after this discount" in page.text
    assert 'name="offer_stacking_stops"' in page.text
    assert "data-catalog-category" in page.text
    assert "Past / day" in page.text


def test_stacking_checkbox_sets_note():
    offer = extract_offer_from_form({"offer_stacking_stops": "yes", "offer_percent": "10"})
    assert offer["stacking_stops"] == "yes"
    assert "Stop stacking" in offer["stacking_note"]
    cleared = extract_offer_from_form({"offer_stacking_stops": "", "offer_stacking_note": "Stop stacking after this discount"})
    assert cleared["stacking_stops"] == ""
    assert cleared["stacking_note"] == ""
