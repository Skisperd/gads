"""Notificações: Telegram (via Bot API, sem dependências extra) e consola."""

from __future__ import annotations

import html
import logging
from dataclasses import dataclass

import httpx
from rich.console import Console
from rich.table import Table

from .config import TelegramConfig
from .models import Listing
from .storage import UpsertResult

log = logging.getLogger("casaradar.notify")


@dataclass
class Event:
    search_name: str
    result: UpsertResult

    @property
    def listing(self) -> Listing:
        return self.result.listing

    @property
    def kind(self) -> str:
        if self.result.is_new:
            return "novo"
        return "preço"


def format_event(ev: Event) -> str:
    l = ev.listing
    title = html.escape(l.title[:120])
    head = "🆕 <b>Novo</b>" if ev.result.is_new else "💶 <b>Mudou de preço</b>"
    price = f"{l.price:,} €".replace(",", " ") if l.price is not None else "preço n/d"
    if l.transaction == "arrendar" and l.price is not None:
        price += "/mês"
    if not ev.result.is_new and ev.result.old_price is not None and l.price is not None:
        old = f"{ev.result.old_price:,} €".replace(",", " ")
        price = f"<s>{old}</s> → {price}"
    bits = [b for b in (l.typology, f"{int(l.area_m2)} m²" if l.area_m2 else None, html.escape(l.location or "")) if b]
    lines = [
        f"{head} · {html.escape(ev.search_name)}",
        f"<a href=\"{html.escape(l.url)}\">{title}</a>",
        f"<b>{price}</b> · {' · '.join(bits)}" if bits else f"<b>{price}</b>",
        f"fonte: {l.source}",
    ]
    if ev.result.duplicate_of:
        others = ", ".join(sorted({k.split(':')[0] for k in ev.result.duplicate_of}))
        lines.append(f"⚠️ parece já estar em: {others}")
    return "\n".join(lines)


class TelegramNotifier:
    API = "https://api.telegram.org"

    def __init__(self, cfg: TelegramConfig, client: httpx.Client | None = None):
        self.cfg = cfg
        self.client = client or httpx.Client(timeout=30)

    @property
    def ready(self) -> bool:
        return bool(self.cfg.enabled and self.cfg.token and self.cfg.chat_id)

    def _call(self, method: str, **payload) -> dict:
        url = f"{self.API}/bot{self.cfg.token}/{method}"
        resp = self.client.post(url, json=payload)
        data = resp.json() if resp.content else {}
        if resp.status_code != 200 or not data.get("ok", False):
            raise RuntimeError(f"Telegram {method} falhou: HTTP {resp.status_code} {data.get('description', resp.text[:200])}")
        return data

    def send_text(self, text: str) -> None:
        self._call("sendMessage", chat_id=self.cfg.chat_id, text=text, parse_mode="HTML", disable_web_page_preview=False)

    def send_event(self, ev: Event) -> None:
        text = format_event(ev)
        l = ev.listing
        if self.cfg.send_photos and l.image_url:
            try:
                self._call("sendPhoto", chat_id=self.cfg.chat_id, photo=l.image_url, caption=text, parse_mode="HTML")
                return
            except RuntimeError as exc:
                log.debug("sendPhoto falhou (%s); a enviar só texto", exc)
        self.send_text(text)

    def send_events(self, events: list[Event]) -> None:
        if not events:
            return
        if len(events) > self.cfg.summary_threshold:
            by_search: dict[str, list[Event]] = {}
            for ev in events:
                by_search.setdefault(ev.search_name, []).append(ev)
            lines = [f"📬 <b>{len(events)} novidades</b> (demasiadas para enviar uma a uma)"]
            for name, evs in by_search.items():
                lines.append(f"\n<b>{html.escape(name)}</b> ({len(evs)})")
                for ev in evs[:15]:
                    l = ev.listing
                    price = f"{l.price:,} €".replace(",", " ") if l.price is not None else "n/d"
                    lines.append(f"• <a href=\"{html.escape(l.url)}\">{html.escape(l.title[:60])}</a> — {price} · {l.typology or ''} · {l.source}")
                if len(evs) > 15:
                    lines.append(f"… e mais {len(evs) - 15}")
            self.send_text("\n".join(lines)[:4000])
            return
        for ev in events:
            self.send_event(ev)

    def get_updates_chat_ids(self) -> list[tuple[str, str]]:
        """Devolve (chat_id, nome) das conversas que já falaram com o bot. Útil para descobrir o chat_id."""
        data = self._call("getUpdates")
        out: dict[str, str] = {}
        for upd in data.get("result", []):
            msg = upd.get("message") or upd.get("channel_post") or {}
            chat = msg.get("chat") or {}
            if chat.get("id") is not None:
                name = chat.get("title") or " ".join(str(chat.get(k) or "") for k in ("first_name", "last_name", "username")).strip()
                out[str(chat["id"])] = name
        return list(out.items())


def print_events(events: list[Event], console: Console | None = None) -> None:
    console = console or Console()
    if not events:
        console.print("[dim]Sem novidades.[/dim]")
        return
    table = Table(title=f"{len(events)} novidades", show_lines=False)
    table.add_column("tipo", style="bold")
    table.add_column("pesquisa")
    table.add_column("fonte")
    table.add_column("preço", justify="right")
    table.add_column("tip.")
    table.add_column("m²", justify="right")
    table.add_column("local")
    table.add_column("título / link")
    for ev in events:
        l = ev.listing
        price = f"{l.price:,}".replace(",", " ") if l.price is not None else "?"
        if not ev.result.is_new and ev.result.old_price is not None:
            price = f"{ev.result.old_price}→{price}"
        flag = " ⚠dup" if ev.result.duplicate_of else ""
        table.add_row(
            ev.kind + flag, ev.search_name, l.source, price, l.typology or "", f"{int(l.area_m2)}" if l.area_m2 else "",
            (l.location or "")[:30], f"[link={l.url}]{l.title[:60]}[/link]",
        )
    console.print(table)
