"""Orquestra uma ronda: para cada pesquisa e fonte, obtém, filtra, guarda e devolve novidades."""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from .config import Config, Search
from .http import Fetcher
from .models import Listing
from .notify import Event
from .sources import get_source
from .storage import Storage

log = logging.getLogger("casaradar.engine")


@dataclass
class RunStats:
    fetched: int = 0
    matched: int = 0
    new: int = 0
    price_changes: int = 0
    errors: list[str] = field(default_factory=list)
    per_source: dict[str, int] = field(default_factory=dict)


def run_once(cfg: Config, storage: Storage, fetcher: Fetcher | None = None, only_search: str | None = None, only_source: str | None = None, first_run_quiet: bool | None = None) -> tuple[list[Event], RunStats]:
    """Executa todas as pesquisas. Devolve os eventos (novos / mudanças de preço) e estatísticas.

    `first_run_quiet`: na primeira execução (base vazia) tudo é "novo"; por defeito não devolvemos
    eventos nesse caso para não inundar o Telegram com centenas de anúncios antigos.
    """
    own_fetcher = fetcher is None
    fetcher = fetcher or Fetcher(delay=cfg.request_delay, timeout=cfg.timeout, user_agent=cfg.user_agent)
    if first_run_quiet is None:
        first_run_quiet = storage.count() == 0
    events: list[Event] = []
    stats = RunStats()
    try:
        for search in cfg.searches:
            if only_search and search.name != only_search:
                continue
            for source_name in search.sources:
                if only_source and source_name != only_source:
                    continue
                try:
                    source = get_source(source_name)
                except KeyError as exc:
                    stats.errors.append(str(exc))
                    log.error("%s", exc)
                    continue
                try:
                    listings = source.fetch(fetcher, search)
                except Exception as exc:  # noqa: BLE001
                    stats.errors.append(f"{source_name}/{search.name}: {exc}")
                    log.exception("[%s] erro inesperado", source_name)
                    continue
                stats.fetched += len(listings)
                stats.per_source[source_name] = stats.per_source.get(source_name, 0) + len(listings)
                for listing in listings:
                    if not search.matches(listing):
                        continue
                    stats.matched += 1
                    res = storage.upsert(listing, search.name)
                    if res.is_new:
                        stats.new += 1
                        if not first_run_quiet:
                            events.append(Event(search.name, res))
                    elif res.old_price is not None and listing.price is not None and listing.price != res.old_price:
                        stats.price_changes += 1
                        events.append(Event(search.name, res))
    finally:
        if own_fetcher:
            fetcher.close()
    if first_run_quiet and stats.new:
        log.info("primeira execução: %d anúncios guardados como base, sem notificar", stats.new)
    return events, stats


def parse_only(html: str, source_name: str, search: Search, url: str) -> list[Listing]:
    return get_source(source_name).parse(html, search, url)
