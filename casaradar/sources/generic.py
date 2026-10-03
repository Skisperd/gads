"""Estratégias de parsing genéricas, usadas como rede de segurança por todas as fontes.

Os portais mudam de markup com frequência. Se o parser específico de um site devolver zero
resultados, tentamos (1) JSON-LD (schema.org) e (2) uma heurística de "cartões": qualquer
bloco com um link para a página de um anúncio e um preço em euros no texto.
"""

from __future__ import annotations

import json
import re
from typing import Iterable

from bs4 import BeautifulSoup, Tag

from ..models import Listing
from ..parse import clean_text, parse_area, parse_price, parse_typology, to_float, to_int
from .base import absolute


def parse_jsonld(html: str, source: str, transaction: str, url: str) -> list[Listing]:
    soup = BeautifulSoup(html, "lxml")
    out: list[Listing] = []
    for script in soup.find_all("script", attrs={"type": "application/ld+json"}):
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue
        for node in _iter_jsonld_nodes(data):
            listing = _jsonld_to_listing(node, source, transaction, url)
            if listing:
                out.append(listing)
    return _dedupe(out)


def _iter_jsonld_nodes(data) -> Iterable[dict]:
    if isinstance(data, list):
        for d in data:
            yield from _iter_jsonld_nodes(d)
    elif isinstance(data, dict):
        t = data.get("@type")
        types = t if isinstance(t, list) else [t]
        if "ItemList" in types:
            for el in data.get("itemListElement", []) or []:
                item = el.get("item", el) if isinstance(el, dict) else None
                if isinstance(item, dict):
                    yield item
        elif any(x in types for x in ("Product", "Offer", "RealEstateListing", "Apartment", "House", "Residence", "Accommodation", "SingleFamilyResidence")):
            yield data
        if "@graph" in data:
            yield from _iter_jsonld_nodes(data["@graph"])


def _jsonld_to_listing(node: dict, source: str, transaction: str, base_url: str) -> Listing | None:
    offers_url = node["offers"].get("url") if isinstance(node.get("offers"), dict) else None
    href = node.get("url") or node.get("@id") or offers_url
    if not href or not isinstance(href, str):
        return None
    offers = node.get("offers")
    if isinstance(offers, list) and offers:
        offers = offers[0]
    price = None
    if isinstance(offers, dict):
        price = to_int(offers.get("price") or (offers.get("priceSpecification") or {}).get("price"))
    if price is None:
        price = to_int(node.get("price"))
    name = clean_text(node.get("name") or node.get("headline") or "")
    area = None
    fs = node.get("floorSize")
    if isinstance(fs, dict):
        area = to_float(fs.get("value"))
    rooms = to_int(node.get("numberOfRooms")) if node.get("numberOfRooms") is not None else None
    image = node.get("image")
    if isinstance(image, list):
        image = image[0] if image else None
    if isinstance(image, dict):
        image = image.get("url") or image.get("contentUrl")
    addr = node.get("address")
    location = None
    if isinstance(addr, dict):
        location = clean_text(" ".join(str(addr.get(k) or "") for k in ("streetAddress", "addressLocality", "addressRegion")))
    elif isinstance(addr, str):
        location = clean_text(addr)
    full = absolute(base_url, href) or href
    return Listing(
        source=source,
        source_id=_id_from_url(full),
        url=full,
        title=name or full,
        transaction=transaction,
        price=price,
        typology=parse_typology(name),
        rooms=rooms,
        area_m2=area,
        location=location or None,
        image_url=image if isinstance(image, str) else None,
        raw={"jsonld": True},
    )


def parse_cards(html: str, source: str, transaction: str, url: str, link_pattern: str, container_tags=("article", "li", "div")) -> list[Listing]:
    """Heurística: para cada link cujo href bate em `link_pattern`, sobe até ao bloco que contém um preço."""
    soup = BeautifulSoup(html, "lxml")
    rx = re.compile(link_pattern)
    out: list[Listing] = []
    seen_hrefs: set[str] = set()
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if not rx.search(href) or href in seen_hrefs:
            continue
        card = _ascend_to_card(a, container_tags)
        if card is None:
            continue
        text = clean_text(card.get_text(" "))
        price = parse_price(text)
        if price is None:
            continue
        seen_hrefs.add(href)
        title = clean_text(a.get("title") or a.get_text(" ")) or _first_heading(card) or text[:80]
        img = card.find("img")
        image = None
        if img:
            image = img.get("data-src") or img.get("src")
            if image and image.startswith("data:"):
                image = None
        full = absolute(url, href) or href
        out.append(
            Listing(
                source=source,
                source_id=_id_from_url(full),
                url=full,
                title=title,
                transaction=transaction,
                price=price,
                typology=parse_typology(text),
                area_m2=parse_area(text),
                image_url=absolute(url, image) if image else None,
                raw={"heuristic": True},
            )
        )
    return _dedupe(out)


def _ascend_to_card(a: Tag, container_tags) -> Tag | None:
    node: Tag | None = a
    for _ in range(8):
        if node is None:
            return None
        if node.name in container_tags and "€" in node.get_text():
            text_len = len(node.get_text(" ", strip=True))
            if text_len < 1500:
                return node
        node = node.parent if isinstance(node.parent, Tag) else None
    return None


def _first_heading(card: Tag) -> str | None:
    for tag in ("h1", "h2", "h3", "h4", "h5", "h6"):
        h = card.find(tag)
        if h:
            return clean_text(h.get_text(" "))
    return None


def _id_from_url(url: str) -> str:
    path = url.split("?")[0].rstrip("/")
    segments = [s for s in path.split("/") if s]
    for seg in reversed(segments):
        if seg.lower() not in ("anuncio", "imovel", "d", "pt", "en"):
            return seg[:120]
    return path[-120:]


def _dedupe(items: list[Listing]) -> list[Listing]:
    seen: set[str] = set()
    out: list[Listing] = []
    for it in items:
        if it.key in seen:
            continue
        seen.add(it.key)
        out.append(it)
    return out
