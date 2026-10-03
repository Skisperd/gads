import json

import httpx

from casaradar.config import TelegramConfig
from casaradar.models import Listing
from casaradar.notify import Event, TelegramNotifier, format_event
from casaradar.storage import UpsertResult


def ev(is_new=True, old_price=None, dupes=None, **kw):
    base = dict(source="imovirtual", source_id="1", url="https://x/1?a=1&b=2", title="T2 <bonito>", transaction="arrendar", price=1350, area_m2=68, typology="T2", location="Arroios, Lisboa", image_url="https://img/1.jpg")
    base.update(kw)
    return Event("T2 Lisboa", UpsertResult(Listing(**base), is_new, old_price, dupes or []))


def test_format_event_new_and_price_change():
    text = format_event(ev())
    assert "🆕" in text and "T2 &lt;bonito&gt;" in text and "1 350 €/mês" in text and "https://x/1?a=1&amp;b=2" in text
    text = format_event(ev(is_new=False, old_price=1500, dupes=["olx:9", "casasapo:3"]))
    assert "Mudou de preço" in text and "<s>1 500 €</s> → 1 350 €/mês" in text and "parece já estar em: casasapo, olx" in text


def test_telegram_sends_photo_then_falls_back(monkeypatch, httpx_mock):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    cfg = TelegramConfig()
    n = TelegramNotifier(cfg)
    assert n.ready
    httpx_mock.add_response(url="https://api.telegram.org/bot123:abc/sendPhoto", status_code=400, json={"ok": False, "description": "bad photo"})
    httpx_mock.add_response(url="https://api.telegram.org/bot123:abc/sendMessage", json={"ok": True})
    n.send_events([ev()])
    reqs = httpx_mock.get_requests()
    assert [r.url.path.split("/")[-1] for r in reqs] == ["sendPhoto", "sendMessage"]
    body = json.loads(reqs[1].content)
    assert body["chat_id"] == "42" and body["parse_mode"] == "HTML" and "T2 Lisboa" in body["text"]


def test_telegram_summary_when_many(monkeypatch, httpx_mock):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "42")
    n = TelegramNotifier(TelegramConfig(summary_threshold=2))
    httpx_mock.add_response(url="https://api.telegram.org/bot123:abc/sendMessage", json={"ok": True})
    n.send_events([ev(source_id=str(i)) for i in range(5)])
    reqs = httpx_mock.get_requests()
    assert len(reqs) == 1
    assert "5 novidades" in json.loads(reqs[0].content)["text"]


def test_not_ready_without_env(monkeypatch):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert not TelegramNotifier(TelegramConfig()).ready
