"""Interface comum a todas as fontes (portais)."""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from ..config import Search
from ..http import BlockedError, Fetcher
from ..models import Listing

log = logging.getLogger("casaradar.sources")


class Source(ABC):
    name: str = "base"
    page_param: str = "page"  # parâmetro de query usado para paginar (None => sem paginação)
    page_size_hint: int = 20  # se uma página devolver menos do que isto, assumimos que é a última

    @abstractmethod
    def build_url(self, search: Search) -> str:
        """URL da primeira página de resultados para esta pesquisa."""

    @abstractmethod
    def parse(self, html: str, search: Search, url: str) -> list[Listing]:
        """Converte o HTML/JSON de uma página de resultados em anúncios normalizados."""

    def paginate(self, url: str, page: int) -> str:
        if page <= 1 or not self.page_param:
            return url
        return set_query_param(url, self.page_param, str(page))

    def start_url(self, search: Search) -> str:
        """URL manual (colado do site) tem prioridade sobre o URL construído."""
        return search.urls.get(self.name) or self.build_url(search)

    def fetch(self, fetcher: Fetcher, search: Search, max_pages: int | None = None) -> list[Listing]:
        base = self.start_url(search)
        pages = max_pages or search.max_pages
        results: list[Listing] = []
        seen: set[str] = set()
        for page in range(1, pages + 1):
            url = self.paginate(base, page)
            try:
                body = fetcher.get(url)
            except BlockedError as exc:
                log.warning("[%s] bloqueado: %s", self.name, exc)
                break
            except Exception as exc:  # noqa: BLE001
                log.warning("[%s] falha ao obter %s: %s", self.name, url, exc)
                break
            items = self.parse(body, search, url)
            new_items = [i for i in items if i.key not in seen]
            seen.update(i.key for i in new_items)
            log.info("[%s] página %d: %d anúncios (%s)", self.name, page, len(new_items), url)
            results.extend(new_items)
            if not new_items or len(items) < self.page_size_hint:
                break
        return results


def set_query_param(url: str, key: str, value: str) -> str:
    parts = urlsplit(url)
    query = [(k, v) for k, v in parse_qsl(parts.query, keep_blank_values=True) if k != key]
    query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query, doseq=True), parts.fragment))


def absolute(base: str, href: str | None) -> str | None:
    if not href:
        return None
    if href.startswith("http://") or href.startswith("https://"):
        return href
    parts = urlsplit(base)
    if href.startswith("//"):
        return f"{parts.scheme}:{href}"
    if href.startswith("/"):
        return f"{parts.scheme}://{parts.netloc}{href}"
    return f"{parts.scheme}://{parts.netloc}/{href}"
