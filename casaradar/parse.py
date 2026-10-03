"""Helpers de parsing de texto comuns a todas as fontes (preço, área, tipologia)."""

from __future__ import annotations

import re
from typing import Any

_PRICE_RE = re.compile(r"(\d{1,3}(?:[.\s ]\d{3})+|\d+)(?:,(\d{1,2}))?\s*€|€\s*(\d{1,3}(?:[.\s ]\d{3})+|\d+)")
_AREA_RE = re.compile(r"(\d+(?:[.,]\d+)?)\s*m\s*(?:²|2)", re.I)
_TYPOLOGY_RE = re.compile(r"\bT\s?(\d{1,2})(?:\s?\+\s?(\d))?\b", re.I)
_INT_RE = re.compile(r"\d+")


def parse_price(text: str | None) -> int | None:
    """Extrai um preço em euros de um texto como '1 250 €', '1.250€/mês' ou '€ 950'."""
    if not text:
        return None
    m = _PRICE_RE.search(text)
    if not m:
        return None
    raw = m.group(1) or m.group(3) or ""
    digits = re.sub(r"[^\d]", "", raw)
    return int(digits) if digits else None


def parse_area(text: str | None) -> float | None:
    """Extrai área em m² de um texto como '65 m²' ou '72,5 m2'."""
    if not text:
        return None
    m = _AREA_RE.search(text)
    if not m:
        return None
    return float(m.group(1).replace(",", "."))


def parse_typology(text: str | None) -> str | None:
    """Extrai a tipologia (T0, T1, T2+1...) de um texto."""
    if not text:
        return None
    m = _TYPOLOGY_RE.search(text)
    if not m:
        return None
    base = f"T{int(m.group(1))}"
    return f"{base}+{m.group(2)}" if m.group(2) else base


def typology_rooms(typology: str | None) -> int | None:
    """T2 -> 2, T2+1 -> 2."""
    if not typology:
        return None
    m = _INT_RE.search(typology)
    return int(m.group()) if m else None


def to_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return int(value)
    digits = re.sub(r"[^\d]", "", str(value).split(",")[0])
    return int(digits) if digits else None


def to_float(value: Any) -> float | None:
    if value is None or value == "":
        return None
    if isinstance(value, (int, float)):
        return float(value)
    m = re.search(r"\d+(?:[.,]\d+)?", str(value))
    return float(m.group().replace(",", ".")) if m else None


def find_key(obj: Any, key: str, max_depth: int = 25) -> Any:
    """Procura recursivamente a primeira ocorrência de `key` em dicts/listas aninhados.

    Útil para blobs JSON (Next.js, estados pré-renderizados) cuja estrutura externa muda
    com frequência, mas cujo nó interessante mantém o nome.
    """
    if max_depth < 0:
        return None
    if isinstance(obj, dict):
        if key in obj:
            return obj[key]
        for v in obj.values():
            found = find_key(v, key, max_depth - 1)
            if found is not None:
                return found
    elif isinstance(obj, list):
        for v in obj:
            found = find_key(v, key, max_depth - 1)
            if found is not None:
                return found
    return None


def clean_text(text: str | None) -> str:
    if not text:
        return ""
    return re.sub(r"\s+", " ", text).strip()
