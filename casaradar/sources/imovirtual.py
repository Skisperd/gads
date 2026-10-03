"""Imovirtual (grupo OLX). A página de resultados é Next.js e embute os anúncios em
<script id="__NEXT_DATA__"> como JSON — muito mais estável do que o HTML.

URL de pesquisa (ex.): https://www.imovirtual.com/pt/resultados/arrendar/apartamento/lisboa/lisboa?priceMax=1500
O `location` pode ser "distrito" ou "distrito/concelho" (ex. "lisboa/cascais").
"""

from __future__ import annotations

import json
import re
from urllib.parse import urlencode

from bs4 import BeautifulSoup

from ..config import Search
from ..models import Listing
from ..parse import clean_text, find_key, parse_area, parse_price, to_float, to_int
from . import generic
from .base import Source, absolute

BASE = "https://www.imovirtual.com"

ESTATE = {"apartamento": "apartamento", "moradia": "moradia", "quarto": "quarto", "terreno": "terreno", "qualquer": "imovel", "outro": "imovel"}
ESTATE_FROM_API = {"FLAT": "apartamento", "HOUSE": "moradia", "ROOM": "quarto", "TERRAIN": "terreno"}
TRANSACTION_FROM_API = {"RENT": "arrendar", "SELL": "comprar"}
ROOMS_ENUM = {1: "ONE", 2: "TWO", 3: "THREE", 4: "FOUR", 5: "FIVE", 6: "SIX", 7: "SEVEN", 8: "EIGHT", 9: "NINE", 10: "TEN"}
ROOMS_FROM_ENUM = {v: k for k, v in ROOMS_ENUM.items()}


class ImovirtualSource(Source):
    name = "imovirtual"
    page_param = "page"
    page_size_hint = 24

    def build_url(self, search: Search) -> str:
        location = search.location_for(self.name).strip("/")
        path = f"/pt/resultados/{search.transaction}/{ESTATE.get(search.property_type, 'imovel')}/{location}"
        params: dict[str, str] = {"limit": "36", "by": "LATEST", "direction": "DESC"}
        if search.price_min is not None:
            params["priceMin"] = str(search.price_min)
        if search.price_max is not None:
            params["priceMax"] = str(search.price_max)
        if search.area_min is not None:
            params["areaMin"] = str(int(search.area_min))
        rooms = [ROOMS_ENUM[r] for r in search.rooms_wanted() if r in ROOMS_ENUM]
        if rooms:
            params["roomsNumber"] = "[" + ",".join(rooms) + "]"
        return f"{BASE}{path}?{urlencode(params)}"

    def parse(self, html: str, search: Search, url: str) -> list[Listing]:
        items = self._parse_next_data(html, search)
        if not items:
            items = self._parse_cards(html, search, url)
        if not items:
            items = generic.parse_jsonld(html, self.name, search.transaction, url)
        if not items:
            items = generic.parse_cards(html, self.name, search.transaction, url, r"/pt/anuncio/")
        return items

    # --- estratégia 1: JSON do Next.js -------------------------------------------------
    def _parse_next_data(self, html: str, search: Search) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        script = soup.find("script", id="__NEXT_DATA__")
        if not script or not script.string:
            return []
        try:
            data = json.loads(script.string)
        except json.JSONDecodeError:
            return []
        search_ads = find_key(data, "searchAds")
        items = None
        if isinstance(search_ads, dict):
            items = search_ads.get("items")
        if not isinstance(items, list):
            return []
        out = []
        for item in items:
            if isinstance(item, dict):
                listing = self._item_to_listing(item, search)
                if listing:
                    out.append(listing)
        return out

    def _item_to_listing(self, item: dict, search: Search) -> Listing | None:
        ad_id = item.get("id")
        slug = item.get("slug")
        if not ad_id and not slug:
            return None
        url = f"{BASE}/pt/anuncio/{slug}" if slug else f"{BASE}/pt/anuncio/{ad_id}"
        price_node = item.get("totalPrice") or item.get("price") or {}
        price = to_int(price_node.get("value") if isinstance(price_node, dict) else price_node)
        if price is None:
            price = to_int(item.get("pricePerMonth") or (item.get("rentPrice") or {}).get("value") if isinstance(item.get("rentPrice"), dict) else None)
        area = to_float(item.get("areaInSquareMeters") or item.get("area"))
        rooms_raw = item.get("roomsNumber")
        rooms = ROOMS_FROM_ENUM.get(rooms_raw) if isinstance(rooms_raw, str) else to_int(rooms_raw)
        location = _location_from_item(item)
        images = item.get("images") or []
        image = None
        if images and isinstance(images[0], dict):
            image = images[0].get("medium") or images[0].get("large") or images[0].get("small")
        transaction = TRANSACTION_FROM_API.get(str(item.get("transaction", "")).upper(), search.transaction)
        return Listing(
            source=self.name,
            source_id=str(ad_id or slug),
            url=url,
            title=clean_text(item.get("title") or ""),
            transaction=transaction,
            price=price,
            property_type=ESTATE_FROM_API.get(str(item.get("estate", "")).upper()),
            rooms=rooms,
            area_m2=area,
            location=location,
            image_url=image,
            published_at=item.get("createdAtFirst") or item.get("dateCreatedFirst") or item.get("dateCreated"),
            raw={"id": ad_id, "private_owner": item.get("isPrivateOwner"), "agency": (item.get("agency") or {}).get("name") if isinstance(item.get("agency"), dict) else None},
        )

    # --- estratégia 2: HTML com data-cy -------------------------------------------------
    def _parse_cards(self, html: str, search: Search, url: str) -> list[Listing]:
        soup = BeautifulSoup(html, "lxml")
        out = []
        for card in soup.select('article[data-cy="listing-item"], article[data-cy="listing-item-pin"]'):
            a = card.select_one('a[data-cy="listing-item-link"]') or card.find("a", href=re.compile(r"/anuncio/"))
            if not a:
                continue
            href = absolute(url, a.get("href")) or ""
            title_el = card.select_one('[data-cy="listing-item-title"]') or card.find(["h2", "h3", "p"])
            text = clean_text(card.get_text(" "))
            out.append(
                Listing(
                    source=self.name,
                    source_id=href.rstrip("/").split("/")[-1],
                    url=href,
                    title=clean_text(title_el.get_text(" ")) if title_el else text[:80],
                    transaction=search.transaction,
                    price=parse_price(text),
                    area_m2=parse_area(text),
                    image_url=(card.find("img") or {}).get("src") if card.find("img") else None,
                    raw={"html": True},
                )
            )
        return out


def _location_from_item(item: dict) -> str | None:
    """Monta "Rua X, Bairro, Freguesia, Concelho" a partir de reverseGeocoding (preferido) ou address."""
    loc = item.get("location") or {}
    if not isinstance(loc, dict):
        return None
    parts: list[str] = []
    rg = loc.get("reverseGeocoding") or {}
    locs = rg.get("locations") if isinstance(rg, dict) else None
    if isinstance(locs, list) and locs:
        by_level = {l.get("locationLevel"): l for l in locs if isinstance(l, dict)}
        for level in ("neighborhood", "parish", "council"):
            node = by_level.get(level)
            if node and node.get("name"):
                parts.append(str(node["name"]))
        if not parts:
            last = locs[-1]
            if isinstance(last, dict):
                parts.append(str(last.get("fullName") or last.get("name") or ""))
    address = loc.get("address") or {}
    if isinstance(address, dict):
        street = address.get("street")
        street_name = street.get("name") if isinstance(street, dict) else street
        if isinstance(street_name, str) and street_name.strip() and not _POSTAL_RE.match(street_name.strip()):
            parts.insert(0, street_name.strip())
        if not parts:
            for k in ("district", "city", "county", "province"):
                node = address.get(k)
                name = node.get("name") if isinstance(node, dict) else node
                if isinstance(name, str) and name:
                    parts.append(name)
    out = ", ".join(dict.fromkeys(p for p in parts if p))
    return out or None


_POSTAL_RE = re.compile(r"^\d{4}-\d{3}")
