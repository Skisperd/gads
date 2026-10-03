"""OLX Portugal. A página de resultados embute o estado em `window.__PRERENDERED_STATE__`
(uma string JSON que contém JSON). Se isso falhar, caímos no HTML dos cartões (data-cy="l-card").

Caminhos de categoria no OLX mudam; se a pesquisa automática devolver zero, cole o URL
da sua pesquisa no OLX em `urls: { olx: "https://www.olx.pt/..." }` no config.
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..config import Search
from ..models import Listing
from ..parse import clean_text, find_key, parse_area, parse_price, parse_typology, to_float, to_int
from . import generic
from .base import Source, absolute

BASE = "https://www.olx.pt"

# CONFIRMAR na primeira execução: caminhos de categoria do OLX PT.
CATEGORY_PATH = {
    ("arrendar", "apartamento"): "imoveis/apartamentos/arrendamento",
    ("comprar", "apartamento"): "imoveis/apartamentos/venda",
    ("arrendar", "moradia"): "imoveis/casas-moradias/arrendamento",
    ("comprar", "moradia"): "imoveis/casas-moradias/venda",
    ("arrendar", "quarto"): "imoveis/quartos-para-alugar",
    ("arrendar", "qualquer"): "imoveis",
    ("comprar", "qualquer"): "imoveis",
}

_STATE_RE = re.compile(r"__PRERENDERED_STATE__\s*=\s*(\"(?:[^\"\\]|\\.)*\")", re.S)
_STATE_OBJ_RE = re.compile(r"__PRERENDERED_STATE__\s*=\s*(\{.*?\})\s*;?\s*</script>", re.S)


class OlxSource(Source):
    name = "olx"
    page_param = "page"
    page_size_hint = 30

    def build_url(self, search: Search) -> str:
        path = CATEGORY_PATH.get((search.transaction, search.property_type)) or CATEGORY_PATH[(search.transaction, "qualquer")]
        location = search.location_for(self.name).strip("/")
        params: dict[str, str] = {"search[order]": "created_at:desc"}
        if search.price_min is not None:
            params["search[filter_float_price:from]"] = str(search.price_min)
        if search.price_max is not None:
            params["search[filter_float_price:to]"] = str(search.price_max)
        return f"{BASE}/{path}/{location}/?{urlencode(params)}"

    def parse(self, html: str, search: Search, url: str) -> list[Listing]:
        items = self._parse_state(html, search)
        if not items:
            items = self._parse_cards(html, search, url)
        if not items:
            items = generic.parse_cards(html, self.name, search.transaction, url, r"/d/anuncio/|/anuncio/")
        return items

    def _parse_state(self, html: str, search: Search) -> list[Listing]:
        data = None
        m = _STATE_RE.search(html)
        if m:
            try:
                data = json.loads(json.loads(m.group(1)))
            except json.JSONDecodeError:
                data = None
        if data is None:
            m = _STATE_OBJ_RE.search(html)
            if m:
                try:
                    data = json.loads(m.group(1))
                except json.JSONDecodeError:
                    data = None
        if data is None:
            return []
        listing_node = find_key(data, "listing")
        ads = None
        if isinstance(listing_node, dict):
            ads = listing_node.get("ads")
            if ads is None and isinstance(listing_node.get("listing"), dict):
                ads = listing_node["listing"].get("ads")
        if ads is None:
            ads = find_key(data, "ads")
        if not isinstance(ads, list):
            return []
        out = []
        for ad in ads:
            if isinstance(ad, dict):
                listing = self._ad_to_listing(ad, search)
                if listing:
                    out.append(listing)
        return out

    def _ad_to_listing(self, ad: dict, search: Search) -> Listing | None:
        ad_id = ad.get("id")
        url = ad.get("url")
        if not ad_id or not url:
            return None
        params = {}
        for p in ad.get("params") or []:
            if not isinstance(p, dict):
                continue
            key = str(p.get("key") or p.get("name") or "").lower()
            val = p.get("value")
            if isinstance(val, dict):
                params[key] = val.get("value") if val.get("value") is not None else val.get("label")
                if "label" in val:
                    params[key + "__label"] = val["label"]
            else:
                params[key] = p.get("normalizedValue") or val
        price = to_int(params.get("price"))
        if price is None:
            price = parse_price(str(params.get("price__label") or ""))
        area = None
        for k, v in params.items():
            if "area" in k and not k.endswith("__label"):
                area = to_float(v)
                if area:
                    break
        typology = None
        for k, v in params.items():
            if any(w in k for w in ("tipolog", "rooms", "quartos")) and v:
                typology = parse_typology(f"T{v}" if str(v).isdigit() else str(v))
                if typology:
                    break
        title = clean_text(ad.get("title") or "")
        if not typology:
            typology = parse_typology(title)
        location_node = ad.get("location") or {}
        location = None
        if isinstance(location_node, dict):
            location = clean_text(", ".join(str(location_node.get(k)) for k in ("cityName", "regionName") if location_node.get(k))) or None
        photos = ad.get("photos") or []
        image = None
        if photos:
            first = photos[0]
            if isinstance(first, dict):
                first = first.get("link") or first.get("url")
            if isinstance(first, str):
                image = first.replace("{width}", "600").replace("{height}", "400")
        return Listing(
            source=self.name,
            source_id=str(ad_id),
            url=absolute(BASE, url) or url,
            title=title,
            transaction=search.transaction,
            price=price,
            typology=typology,
            area_m2=area,
            location=location,
            image_url=image,
            published_at=ad.get("createdTime") or ad.get("lastRefreshTime"),
            raw={"id": ad_id},
        )

    def _parse_cards(self, html: str, search: Search, url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for card in soup.select('div[data-cy="l-card"], [data-testid="l-card"]'):
            a = card.find("a", href=True)
            if not a:
                continue
            href = absolute(url, a["href"]) or ""
            text = clean_text(card.get_text(" "))
            price_el = card.select_one('[data-testid="ad-price"]')
            title_el = card.find(["h4", "h6", "h3"])
            loc_el = card.select_one('[data-testid="location-date"]')
            ad_id = card.get("id") or href.rstrip("/").split("-")[-1].replace(".html", "")
            out.append(
                Listing(
                    source=self.name,
                    source_id=ad_id,
                    url=href,
                    title=clean_text(title_el.get_text(" ")) if title_el else text[:80],
                    transaction=search.transaction,
                    price=parse_price(price_el.get_text(" ") if price_el else text),
                    area_m2=parse_area(text),
                    location=clean_text(loc_el.get_text(" ")).split(" - ")[0] if loc_el else None,
                    image_url=(card.find("img") or {}).get("src") if card.find("img") else None,
                    raw={"html": True},
                )
            )
        return out
