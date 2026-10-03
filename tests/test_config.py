import pytest

from casaradar.config import Config, ConfigError, Search
from casaradar.models import Listing


def mk(**kw):
    base = dict(source="s", source_id="1", url="https://x/1", title="Apartamento T2", transaction="arrendar", price=1200, area_m2=60, typology="T2")
    base.update(kw)
    return Listing(**base)


def test_matches_basic(search):
    assert search.matches(mk())
    assert not search.matches(mk(price=1600))
    assert not search.matches(mk(price=700))
    assert not search.matches(mk(area_m2=40))
    assert not search.matches(mk(typology="T3", title="T3"))
    assert search.matches(mk(typology="T2+1", title="T2+1"))
    assert not search.matches(mk(property_type="moradia"))
    assert search.matches(mk(property_type=None))


def test_unknown_fields_pass_unless_strict(search):
    assert search.matches(mk(price=None, area_m2=None, typology=None, title="Apartamento bonito"))
    strict = Search(name="s", typology=["T2"], price_max=1500, area_min=50, strict=True)
    assert not strict.matches(mk(price=None))
    assert not strict.matches(mk(area_m2=None))
    assert not strict.matches(mk(typology=None, title="sem tipologia"))
    assert strict.matches(mk())


def test_exclude_words():
    s = Search(name="s", exclude_words=["Quarto", "estudantes"])
    assert not s.matches(mk(title="Quarto em T3 partilhado"))
    assert not s.matches(mk(title="T1", location="Residência de Estudantes"))
    assert s.matches(mk(title="T2 soalheiro"))


def test_location_for_and_rooms(search):
    assert search.location_for("imovirtual") == "lisboa/lisboa"
    assert search.location_for("olx") == "lisboa"
    assert search.rooms_wanted() == [1, 2]
    assert Search(name="x", location="porto").location_for("casasapo") == "porto"
    assert Search(name="x", typology=["t2+1", "T0"]).rooms_wanted() == [0, 2]


def test_listing_derives_typology_and_rooms():
    l = Listing(source="s", source_id=1, url="u", title="Moradia T3 com jardim", transaction="comprar")
    assert l.typology == "T3" and l.rooms == 3 and l.source_id == "1"
    l2 = Listing(source="s", source_id="2", url="u", title="x", transaction="RENT", rooms=2)
    assert l2.typology == "T2" and l2.transaction == "comprar"  # desconhecido -> comprar salvo se contiver 'arrend'
    l3 = Listing(source="s", source_id="3", url="u", title="x", transaction="arrendamento")
    assert l3.transaction == "arrendar"


def test_fingerprint_groups_similar_listings():
    a = mk(source="olx", source_id="1", price=1200, area_m2=70, location="Lisboa")
    b = mk(source="imovirtual", source_id="9", price=1210, area_m2=72, location="Lisboa")
    c = mk(source="imovirtual", source_id="8", price=1500, area_m2=72, location="Lisboa")
    assert a.fingerprint == b.fingerprint
    assert a.fingerprint != c.fingerprint


def test_config_from_dict_validation():
    with pytest.raises(ConfigError):
        Config.from_dict({})
    with pytest.raises(ConfigError):
        Config.from_dict({"searches": [{"name": "a"}, {"name": "a"}]})
    with pytest.raises(ConfigError):
        Config.from_dict({"searches": [{"name": "a", "transaction": "alugar"}]})
    with pytest.raises(ConfigError):
        Config.from_dict({"searches": [{"name": "a", "preco_max": 1}]})
    cfg = Config.from_dict({"searches": [{"name": "a", "typology": ["t2"]}], "telegram": {"summary_threshold": 3}})
    assert cfg.searches[0].typology == ["T2"] and cfg.telegram.summary_threshold == 3


def test_example_config_loads():
    from pathlib import Path
    cfg = Config.load(Path(__file__).resolve().parent.parent / "config.example.yaml")
    assert len(cfg.searches) == 2
    assert cfg.searches[0].location_for("imovirtual") == "lisboa/lisboa"
