import re

import pytest

from casaradar.config import Config
from casaradar.engine import run_once
from casaradar.http import Fetcher
from casaradar.models import Listing
from casaradar.storage import Storage


def mk(**kw):
    base = dict(source="olx", source_id="1", url="https://x/1", title="T2 Lisboa", transaction="arrendar", price=1200, area_m2=60, location="Lisboa")
    base.update(kw)
    return Listing(**base)


def test_storage_upsert_new_then_price_change_and_duplicates():
    st = Storage(":memory:")
    r1 = st.upsert(mk(), "s")
    assert r1.is_new and r1.old_price is None and r1.duplicate_of == []
    r2 = st.upsert(mk(), "s")
    assert not r2.is_new and r2.old_price == 1200
    r3 = st.upsert(mk(price=1100), "s")
    assert not r3.is_new and r3.old_price == 1200
    hist = st.conn.execute("SELECT price FROM price_history WHERE key='olx:1' ORDER BY rowid").fetchall()
    assert [h[0] for h in hist] == [1200, 1100]
    # mesmo imóvel noutro site -> marcado como possível duplicado, não escondido
    r4 = st.upsert(mk(source="imovirtual", source_id="77", price=1110, area_m2=62), "s")
    assert r4.is_new and r4.duplicate_of == ["olx:1"]
    assert st.count() == 2
    assert len(st.recent("s")) == 2 and st.recent("outra") == []


def _cfg(tmp_path, fixture_html_by_source):
    return Config.from_dict({
        "searches": [{
            "name": "t2",
            "transaction": "arrendar",
            "property_type": "apartamento",
            "location": "lisboa",
            "typology": ["T1", "T2"],
            "price_max": 1500,
            "sources": list(fixture_html_by_source),
            "max_pages": 1,
        }],
        "storage": str(tmp_path / "db.sqlite"),
        "request_delay": 0,
    })




def test_engine_first_run_quiet_then_new_and_price_change(tmp_path, fixture, httpx_mock):
    cfg = _cfg(tmp_path, {"imovirtual": 1, "olx": 1})
    storage = Storage(cfg.storage)
    httpx_mock.add_response(url=re.compile(r"https://www\.imovirtual\.com/.*"), text=fixture("imovirtual_next.html"), is_reusable=True)
    httpx_mock.add_response(url=re.compile(r"https://www\.olx\.pt/.*"), text=fixture("olx_state.html"), is_reusable=True)
    fetcher = Fetcher(delay=0, retries=0)

    events, stats = run_once(cfg, storage, fetcher=fetcher)
    # 3 imovirtual + 2 olx obtidos; filtro: T1/T2 até 1500 -> imov T2 1350, imov T1 1100, olx T2 1200 (quarto 450 sem tipologia passa: campo desconhecido)
    assert stats.fetched == 5 and stats.matched == 4 and stats.new == 4
    assert events == []  # primeira execução é silenciosa

    events, stats = run_once(cfg, storage, fetcher=fetcher)
    assert events == [] and stats.new == 0 and stats.price_changes == 0

    # agora o OLX muda o preço do T2 e aparece um anúncio novo
    html = fixture("olx_state.html").replace('\\"value\\":1200', '\\"value\\":1150').replace('\\"id\\":111,', '\\"id\\":112,')
    httpx_mock.reset()
    httpx_mock.add_response(url=re.compile(r"https://www\.imovirtual\.com/.*"), text=fixture("imovirtual_next.html"), is_reusable=True)
    httpx_mock.add_response(url=re.compile(r"https://www\.olx\.pt/.*"), text=html, is_reusable=True)
    events, stats = run_once(cfg, storage, fetcher=fetcher)
    kinds = sorted((e.kind, e.listing.source_id) for e in events)
    assert kinds == [("novo", "112"), ("preço", "987654321")]
    change = next(e for e in events if e.kind == "preço")
    assert change.result.old_price == 1200 and change.listing.price == 1150
    fetcher.close()


def test_engine_handles_blocked_source(tmp_path, fixture, httpx_mock):
    cfg = _cfg(tmp_path, {"imovirtual": 1, "casasapo": 1})
    storage = Storage(cfg.storage)
    httpx_mock.add_response(url=re.compile(r"https://www\.imovirtual\.com/.*"), text=fixture("imovirtual_next.html"))
    httpx_mock.add_response(url=re.compile(r"https://casa\.sapo\.pt/.*"), status_code=403, text="forbidden")
    fetcher = Fetcher(delay=0, retries=0)
    events, stats = run_once(cfg, storage, fetcher=fetcher, first_run_quiet=False)
    assert stats.per_source == {"imovirtual": 3, "casasapo": 0}
    assert stats.errors == []  # bloqueio é aviso, não erro fatal
    assert len(events) == 2
    fetcher.close()


def test_fetcher_detects_captcha(httpx_mock):
    from casaradar.http import BlockedError
    httpx_mock.add_response(url=re.compile(r"https://www\.idealista\.pt/.*"), status_code=200, text="<html><script src='https://ct.captcha-delivery.com/c.js'></script></html>")
    f = Fetcher(delay=0, retries=0)
    with pytest.raises(BlockedError):
        f.get("https://www.idealista.pt/arrendar-casas/lisboa/")
    f.close()
