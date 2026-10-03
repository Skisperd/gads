import pytest

from casaradar.config import Search
from casaradar.sources import SOURCES, get_source
from casaradar.sources import generic
from casaradar.sources.base import set_query_param


def test_imovirtual_next_data(fixture, search):
    src = get_source("imovirtual")
    items = src.parse(fixture("imovirtual_next.html"), search, src.build_url(search))
    assert len(items) == 3
    a = items[0]
    assert a.key == "imovirtual:12345678"
    assert a.url == "https://www.imovirtual.com/pt/anuncio/apartamento-t2-arroios-ID1abcd"
    assert a.price == 1350 and a.area_m2 == 68.5 and a.typology == "T2" and a.rooms == 2
    assert a.property_type == "apartamento" and a.transaction == "arrendar"
    assert a.location == "Arroios, Lisboa"
    assert a.image_url.endswith("1-medium.jpg")
    b = items[1]
    assert b.location == "Campo de Ourique, Lisboa" and b.typology == "T1"
    c = items[2]
    assert c.property_type == "moradia" and c.transaction == "comprar" and c.location is None


def test_imovirtual_url(search):
    url = get_source("imovirtual").build_url(search)
    assert url.startswith("https://www.imovirtual.com/pt/resultados/arrendar/apartamento/lisboa/lisboa?")
    assert "priceMax=1500" in url and "priceMin=800" in url and "areaMin=50" in url
    assert "roomsNumber=%5BONE%2CTWO%5D" in url
    assert get_source("imovirtual").paginate(url, 2).endswith("&page=2")


def test_olx_prerendered_state(fixture, search):
    src = get_source("olx")
    items = src.parse(fixture("olx_state.html"), search, src.build_url(search))
    assert len(items) == 2
    a = items[0]
    assert a.key == "olx:987654321"
    assert a.price == 1200 and a.area_m2 == 72 and a.typology == "T2"
    assert a.location == "Lisboa, Lisboa"
    assert a.image_url == "https://ireland.apollo.olxcdn.com/v1/files/xyz/image;s=600x400"
    b = items[1]
    assert b.url == "https://www.olx.pt/d/anuncio/quarto-IDqqq.html" and b.price == 450 and b.typology is None


def test_olx_cards_fallback(fixture, search):
    src = get_source("olx")
    items = src.parse(fixture("olx_cards.html"), search, "https://www.olx.pt/imoveis/")
    assert len(items) == 1
    a = items[0]
    assert a.source_id == "55555" and a.price == 1650 and a.typology == "T3" and a.area_m2 == 95
    assert a.location == "Lisboa" and a.url == "https://www.olx.pt/d/anuncio/t3-alvalade-IDzzz.html"


def test_casasapo_cards(fixture, search):
    src = get_source("casasapo")
    url = src.build_url(search)
    assert url == "https://casa.sapo.pt/alugar-apartamentos/lisboa/t1-t2/?gp=1500&cp=800"
    items = src.parse(fixture("casasapo.html"), search, url)
    assert len(items) == 2
    a, b = items
    assert a.source_id == "sapo-100" and a.price == 1300 and a.typology == "T2" and a.area_m2 == 65
    assert a.location == "Arroios, Lisboa" and a.url == "https://casa.sapo.pt/alugar-apartamento-t2-lisboa-arroios/abc-100/"
    assert a.image_url == "https://img.sapo/100.jpg"
    assert b.price == 1750 and b.typology == "T3" and b.image_url is None
    assert src.paginate(url, 3).endswith("&pn=3")


def test_supercasa_jsonld_fallback(fixture, search):
    src = get_source("supercasa")
    url = src.build_url(search)
    assert url == "https://supercasa.pt/arrendar-apartamentos/lisboa/t1,t2?preco-max=1500&preco-min=800"
    items = src.parse(fixture("generic_jsonld.html"), search, url)
    assert len(items) == 2
    a, b = items
    assert a.price == 1250 and a.typology == "T2" and a.url == "https://supercasa.pt/apartamento-t2-lumiar-123456"
    assert a.source_id == "apartamento-t2-lumiar-123456"
    assert b.url == "https://supercasa.pt/t1-parque-das-nacoes-654321" and b.area_m2 == 52 and b.rooms == 1 and b.location == "Lisboa"


def test_generic_cards_heuristic(fixture):
    items = generic.parse_cards(fixture("generic_cards.html"), "x", "arrendar", "https://example.pt/lista", r"/imovel-")
    assert len(items) == 1
    a = items[0]
    assert a.url == "https://example.pt/imovel-t2-lisboa-77777" and a.price == 1400 and a.area_m2 == 70 and a.typology == "T2"
    assert a.title == "T2 junto ao metro" and a.image_url == "https://example.pt/img/77777.jpg"


def test_idealista(fixture, search):
    src = get_source("idealista")
    url = src.build_url(search)
    assert url == "https://www.idealista.pt/arrendar-apartamentos/lisboa/com-preco-max_1500,preco-min_800,tamanho-min_50,t1,t2/?ordem=atualizado-desc"
    assert src.paginate(url, 2) == "https://www.idealista.pt/arrendar-apartamentos/lisboa/com-preco-max_1500,preco-min_800,tamanho-min_50,t1,t2/pagina-2.htm?ordem=atualizado-desc"
    items = src.parse(fixture("idealista.html"), search, url)
    assert len(items) == 1
    a = items[0]
    assert a.source_id == "31122334" and a.url == "https://www.idealista.pt/imovel/31122334/"
    assert a.price == 1450 and a.typology == "T2" and a.area_m2 == 70 and a.location == "Arroios, Lisboa"
    assert a.image_url == "https://img.idealista/1.jpg"


def test_manual_url_override_wins():
    s = Search(name="x", urls={"olx": "https://www.olx.pt/imoveis/qualquer-coisa/?a=1"})
    src = get_source("olx")
    assert src.start_url(s) == "https://www.olx.pt/imoveis/qualquer-coisa/?a=1"
    assert src.paginate(src.start_url(s), 2) == "https://www.olx.pt/imoveis/qualquer-coisa/?a=1&page=2"


def test_set_query_param_replaces():
    assert set_query_param("https://a.pt/x?page=1&q=2", "page", "5") == "https://a.pt/x?q=2&page=5"


@pytest.mark.parametrize("name", list(SOURCES))
def test_every_source_handles_garbage(name, search):
    src = get_source(name)
    assert src.parse("<html><body>nada aqui</body></html>", search, src.build_url(search)) == []
    assert src.parse("", search, src.build_url(search)) == []


def test_unknown_source():
    with pytest.raises(KeyError):
        get_source("zillow")


def test_casasapo_unwraps_counter_redirect():
    from casaradar.sources.casasapo import listing_id_from_url, unwrap_redirect
    wrapped = "https://gespub.casa.sapo.pt/v3/webinterface/client/counter.aspx?c=1&p=1092826&s=0&l=https://casa.sapo.pt/alugar-apartamento-lisboa-b5014dd5-80c9-489c-8f53-e34227f501a3.html?g3pid=1092826"
    assert unwrap_redirect(wrapped) == "https://casa.sapo.pt/alugar-apartamento-lisboa-b5014dd5-80c9-489c-8f53-e34227f501a3.html"
    assert unwrap_redirect("https://casa.sapo.pt/x.html") == "https://casa.sapo.pt/x.html"
    assert listing_id_from_url("https://casa.sapo.pt/alugar-apartamento-t2-lisboa-estrela-2b4ca11d-1c9a-11f1-a463-060000000052.html") == "2b4ca11d-1c9a-11f1-a463-060000000052"
    assert listing_id_from_url("https://casa.sapo.pt/abc-100/") == "abc-100"


def test_imovirtual_location_from_reverse_geocoding():
    from casaradar.sources.imovirtual import _location_from_item
    item = {"location": {"address": {"street": {"name": "1700-117 | Alvalade, Lisboa, Rua Conde de Sabugosa"}, "city": None},
                         "reverseGeocoding": {"locations": [
                             {"locationLevel": "district", "name": "Lisboa"},
                             {"locationLevel": "council", "name": "Lisboa"},
                             {"locationLevel": "parish", "name": "Alvalade"},
                             {"locationLevel": "neighborhood", "name": "Alvalade"}]}}}
    assert _location_from_item(item) == "Alvalade, Lisboa"
    item["location"]["address"]["street"]["name"] = "Avenida Professor Gama Pinto"
    item["location"]["reverseGeocoding"]["locations"][-1]["name"] = "Campo Grande"
    assert _location_from_item(item) == "Avenida Professor Gama Pinto, Campo Grande, Alvalade, Lisboa"
    assert _location_from_item({"location": {}}) is None
