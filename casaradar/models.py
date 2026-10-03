"""Modelo de dados normalizado para um anúncio, independente da fonte."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from dataclasses import asdict, dataclass, field
from typing import Any

from .parse import parse_typology, typology_rooms

TRANSACTIONS = ("arrendar", "comprar")
PROPERTY_TYPES = ("apartamento", "moradia", "quarto", "terreno", "outro")


def slugify(text: str | None) -> str:
    if not text:
        return ""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    text = re.sub(r"[^a-zA-Z0-9]+", "-", text.lower()).strip("-")
    return text


@dataclass
class Listing:
    source: str
    source_id: str
    url: str
    title: str
    transaction: str
    price: int | None = None
    property_type: str | None = None
    typology: str | None = None
    rooms: int | None = None
    area_m2: float | None = None
    location: str | None = None
    image_url: str | None = None
    published_at: str | None = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False, compare=False)

    def __post_init__(self) -> None:
        self.source_id = str(self.source_id)
        self.title = (self.title or "").strip() or self.url
        if self.transaction not in TRANSACTIONS:
            self.transaction = "arrendar" if "arrend" in (self.transaction or "") else "comprar"
        if not self.typology:
            self.typology = parse_typology(self.title)
        if self.typology:
            self.typology = self.typology.upper().replace(" ", "")
        if self.rooms is None:
            self.rooms = typology_rooms(self.typology)
        if self.typology is None and self.rooms is not None:
            self.typology = f"T{self.rooms}"

    @property
    def key(self) -> str:
        return f"{self.source}:{self.source_id}"

    @property
    def fingerprint(self) -> str:
        """Assinatura aproximada para detectar o mesmo imóvel publicado em sites diferentes.

        Combina transação, tipologia, preço arredondado (±25 €) e área arredondada (±5 m²)
        com o concelho/local normalizado. Não é perfeita: serve para marcar "possível duplicado",
        nunca para esconder anúncios.
        """
        price_bucket = round(self.price / 25) if self.price else "?"
        area_bucket = round(self.area_m2 / 5) if self.area_m2 else "?"
        loc = slugify(self.location)[:40]
        base = f"{self.transaction}|{self.typology or self.rooms or '?'}|{price_bucket}|{area_bucket}|{loc}"
        return hashlib.sha1(base.encode()).hexdigest()[:16]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d.pop("raw", None)
        return d

    def short(self) -> str:
        bits = [self.typology or "", f"{int(self.area_m2)} m²" if self.area_m2 else "", f"{self.price:,} €".replace(",", " ") if self.price else "preço?"]
        return " · ".join(b for b in bits if b)
