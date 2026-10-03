from casaradar.parse import find_key, parse_area, parse_price, parse_typology, typology_rooms


def test_parse_price_formats():
    assert parse_price("1 250 €") == 1250
    assert parse_price("1.250€/mês") == 1250
    assert parse_price("€ 950") == 950
    assert parse_price("650.000 €") == 650000
    assert parse_price("1 300 €") == 1300
    assert parse_price("sem preço") is None
    assert parse_price(None) is None


def test_parse_area():
    assert parse_area("65 m²") == 65
    assert parse_area("72,5 m2") == 72.5
    assert parse_area("área bruta 90 m² · 3 wc") == 90
    assert parse_area("T2") is None


def test_parse_typology():
    assert parse_typology("Apartamento T2 em Arroios") == "T2"
    assert parse_typology("t3 renovado") == "T3"
    assert parse_typology("T2+1 com terraço") == "T2+1"
    assert parse_typology("Moradia 4 quartos") is None
    assert typology_rooms("T2+1") == 2
    assert typology_rooms(None) is None


def test_find_key_nested():
    data = {"a": [{"b": {"searchAds": {"items": [1]}}}]}
    assert find_key(data, "searchAds") == {"items": [1]}
    assert find_key(data, "nope") is None
