"""Supercasa. Markup parecido com o Casa Sapo (mesmo grupo), cartões `.property`.

URL de pesquisa (ex.): https://supercasa.pt/arrendar-apartamentos/lisboa
Se o URL construído não devolver resultados, cole o URL da sua pesquisa em `urls: { supercasa: ... }`.
"""

from __future__ import annotations

from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..config import Search
from ..models import Listing
from ..parse import clean_text, parse_area, parse_price, parse_typology
from . import generic
from .base import Source, absolute

BASE = "https://supercasa.pt"
KIND = {"apartamento": "apartamentos", "moradia": "moradias", "quarto": "quartos", "terreno": "terrenos", "qualquer": "casas", "outro": "casas"}


class SupercasaSource(Source):
    name = "supercasa"
    page_param = "pagina"
    page_size_hint = 20

    def build_url(self, search: Search) -> str:
        location = search.location_for(self.name).strip("/")
        path = f"/{search.transaction}-{KIND.get(search.property_type, 'casas')}/{location}"
        rooms = search.rooms_wanted()
        if rooms:
            path += "/" + ",".join(f"t{r}" for r in rooms)
        params: dict[str, str] = {}
        if search.price_max is not None:
            params["preco-max"] = str(search.price_max)
        if search.price_min is not None:
            params["preco-min"] = str(search.price_min)
        query = f"?{urlencode(params)}" if params else ""
        return f"{BASE}{path}{query}"

    def parse(self, html: str, search: Search, url: str) -> list[Listing]:
        items = self._parse_properties(html, search, url)
        if not items:
            items = generic.parse_jsonld(html, self.name, search.transaction, url)
        if not items:
            items = generic.parse_cards(html, self.name, search.transaction, url, r"supercasa\.pt/.+-\d+|^/[a-z0-9-]+-\d+$")
        return items

    def _parse_properties(self, html: str, search: Search, url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for card in soup.select("div.property, article.property, div[class*='property-card'], li.property"):
            a = card.select_one("a.property-link, a.property-info, a[href^='/'], a[href*='supercasa.pt']")
            if not a or not a.get("href"):
                continue
            href = absolute(url, a["href"]) or ""
            text = clean_text(card.get_text(" "))
            title_el = card.select_one(".property-type, .property-title, h2, h3")
            loc_el = card.select_one(".property-location, .property-address")
            price_el = card.select_one(".property-price-value, .property-price")
            img = card.find("img")
            image = (img.get("data-src") or img.get("src")) if img else None
            source_id = card.get("id") or card.get("data-id") or href.rstrip("/").split("/")[-1]
            out.append(
                Listing(
                    source=self.name,
                    source_id=str(source_id),
                    url=href,
                    title=clean_text(title_el.get_text(" ")) if title_el else text[:80],
                    transaction=search.transaction,
                    price=parse_price(price_el.get_text(" ") if price_el else text),
                    typology=parse_typology(text),
                    area_m2=parse_area(text),
                    location=clean_text(loc_el.get_text(" ")) if loc_el else None,
                    image_url=absolute(url, image) if image and not image.startswith("data:") else None,
                    raw={"html": True},
                )
            )
        return out
