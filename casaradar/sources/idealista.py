"""Idealista (experimental, desligado por defeito).

O Idealista usa proteção anti-bot agressiva (DataDome). Pedidos simples costumam receber 403
ou uma página de captcha; quando isso acontece registamos um aviso e seguimos em frente.
Para o ativar, acrescente "idealista" à lista `sources` da pesquisa.

URL de pesquisa (ex.): https://www.idealista.pt/arrendar-casas/lisboa/com-preco-max_1500,t2/?ordem=atualizado-desc
Paginação: /pagina-2.htm antes da query string.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit, urlunsplit

from bs4 import BeautifulSoup

from ..config import Search
from ..models import Listing
from ..parse import clean_text, parse_area, parse_price, parse_typology
from . import generic
from .base import Source, absolute

BASE = "https://www.idealista.pt"
ACTION = {"arrendar": "arrendar", "comprar": "comprar"}
KIND = {"apartamento": "apartamentos", "moradia": "moradias", "quarto": "quartos", "terreno": "terrenos", "qualquer": "casas", "outro": "casas"}


class IdealistaSource(Source):
    name = "idealista"
    page_param = ""  # paginação pelo caminho, ver paginate()
    page_size_hint = 30

    def build_url(self, search: Search) -> str:
        location = search.location_for(self.name).strip("/")
        filters = []
        if search.price_max is not None:
            filters.append(f"com-preco-max_{search.price_max}")
        if search.price_min is not None:
            filters.append(f"preco-min_{search.price_min}")
        if search.area_min is not None:
            filters.append(f"tamanho-min_{int(search.area_min)}")
        for r in search.rooms_wanted():
            filters.append(f"t{r}")
        seg = ("/" + ",".join(filters)) if filters else ""
        return f"{BASE}/{ACTION[search.transaction]}-{KIND.get(search.property_type, 'casas')}/{location}{seg}/?ordem=atualizado-desc"

    def paginate(self, url: str, page: int) -> str:
        if page <= 1:
            return url
        parts = urlsplit(url)
        path = re.sub(r"/pagina-\d+\.htm$", "", parts.path.rstrip("/"))
        return urlunsplit((parts.scheme, parts.netloc, f"{path}/pagina-{page}.htm", parts.query, ""))

    def parse(self, html: str, search: Search, url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for card in soup.select("article.item"):
            a = card.select_one("a.item-link")
            if not a or not a.get("href"):
                continue
            href = absolute(url, a["href"]) or ""
            text = clean_text(card.get_text(" "))
            price_el = card.select_one(".item-price")
            details = [clean_text(d.get_text(" ")) for d in card.select(".item-detail")]
            details_text = " ".join(details)
            img = card.select_one("img")
            image = (img.get("data-ondemand-img") or img.get("src")) if img else None
            source_id = card.get("data-element-id") or card.get("data-adid") or href.rstrip("/").split("/")[-1]
            title = clean_text(a.get("title") or a.get_text(" "))
            location = None
            if "," in title:
                location = title.split(",", 1)[1].strip()
            out.append(
                Listing(
                    source=self.name,
                    source_id=str(source_id),
                    url=href,
                    title=title,
                    transaction=search.transaction,
                    price=parse_price(price_el.get_text(" ") if price_el else text),
                    typology=parse_typology(details_text) or parse_typology(title),
                    area_m2=parse_area(details_text) or parse_area(text),
                    location=location,
                    image_url=image if image and not image.startswith("data:") else None,
                    raw={"html": True, "details": details},
                )
            )
        if not out:
            out = generic.parse_cards(html, self.name, search.transaction, url, r"/imovel/\d+")
        return out
