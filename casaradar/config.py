"""Leitura e validação do config.yaml."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from .models import Listing, PROPERTY_TYPES, TRANSACTIONS

DEFAULT_SOURCES = ["imovirtual", "casasapo", "olx", "supercasa"]


class ConfigError(Exception):
    pass


@dataclass
class Search:
    name: str
    transaction: str = "arrendar"
    property_type: str = "apartamento"
    location: str | dict[str, str] = "lisboa"
    typology: list[str] = field(default_factory=list)
    price_min: int | None = None
    price_max: int | None = None
    area_min: float | None = None
    sources: list[str] = field(default_factory=lambda: list(DEFAULT_SOURCES))
    urls: dict[str, str] = field(default_factory=dict)
    max_pages: int = 3
    strict: bool = False
    exclude_words: list[str] = field(default_factory=list)

    def __post_init__(self) -> None:
        if self.transaction not in TRANSACTIONS:
            raise ConfigError(f"pesquisa '{self.name}': transaction deve ser um de {TRANSACTIONS}")
        if self.property_type not in PROPERTY_TYPES and self.property_type != "qualquer":
            raise ConfigError(f"pesquisa '{self.name}': property_type deve ser um de {PROPERTY_TYPES} ou 'qualquer'")
        self.typology = [t.upper().replace(" ", "") for t in self.typology]
        self.sources = [s.lower() for s in self.sources]
        self.exclude_words = [w.lower() for w in self.exclude_words]

    def location_for(self, source: str) -> str:
        if isinstance(self.location, dict):
            return self.location.get(source) or self.location.get("default") or next(iter(self.location.values()))
        return self.location

    def rooms_wanted(self) -> list[int]:
        out: list[int] = []
        for t in self.typology:
            digits = "".join(ch for ch in t.split("+")[0] if ch.isdigit())
            if digits:
                out.append(int(digits))
        return sorted(set(out))

    def matches(self, listing: Listing) -> bool:
        """Filtro local. Campos desconhecidos passam, salvo em modo strict."""
        unknown_ok = not self.strict

        if listing.price is None:
            if not unknown_ok:
                return False
        else:
            if self.price_min is not None and listing.price < self.price_min:
                return False
            if self.price_max is not None and listing.price > self.price_max:
                return False

        if self.area_min is not None:
            if listing.area_m2 is None:
                if not unknown_ok:
                    return False
            elif listing.area_m2 < self.area_min:
                return False

        if self.typology:
            if listing.typology is None and listing.rooms is None:
                if not unknown_ok:
                    return False
            else:
                base = (listing.typology or f"T{listing.rooms}").split("+")[0]
                wanted = {t.split("+")[0] for t in self.typology}
                if base not in wanted:
                    return False

        if self.property_type != "qualquer" and listing.property_type and listing.property_type != self.property_type:
            return False

        if self.exclude_words:
            hay = f"{listing.title} {listing.location or ''}".lower()
            if any(w in hay for w in self.exclude_words):
                return False
        return True


@dataclass
class TelegramConfig:
    token_env: str = "TELEGRAM_BOT_TOKEN"
    chat_id_env: str = "TELEGRAM_CHAT_ID"
    enabled: bool = True
    send_photos: bool = True
    summary_threshold: int = 12

    @property
    def token(self) -> str | None:
        return os.environ.get(self.token_env) or None

    @property
    def chat_id(self) -> str | None:
        return os.environ.get(self.chat_id_env) or None


@dataclass
class Config:
    searches: list[Search]
    telegram: TelegramConfig = field(default_factory=TelegramConfig)
    storage: str = "data/casaradar.db"
    request_delay: float = 2.0
    timeout: float = 30.0
    user_agent: str | None = None

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Config":
        if not isinstance(data, dict) or "searches" not in data:
            raise ConfigError("config precisa de uma lista 'searches'")
        searches = [Search(**_known_fields(Search, s)) for s in data["searches"] or []]
        if not searches:
            raise ConfigError("defina pelo menos uma pesquisa em 'searches'")
        names = [s.name for s in searches]
        if len(set(names)) != len(names):
            raise ConfigError("cada pesquisa precisa de um 'name' único")
        tg = TelegramConfig(**_known_fields(TelegramConfig, data.get("telegram") or {}))
        return cls(
            searches=searches,
            telegram=tg,
            storage=data.get("storage", "data/casaradar.db"),
            request_delay=float(data.get("request_delay", 2.0)),
            timeout=float(data.get("timeout", 30.0)),
            user_agent=data.get("user_agent"),
        )

    @classmethod
    def load(cls, path: str | Path) -> "Config":
        p = Path(path)
        if not p.exists():
            raise ConfigError(f"ficheiro de configuração não encontrado: {p} (corra 'casaradar init')")
        with p.open("r", encoding="utf-8") as fh:
            data = yaml.safe_load(fh) or {}
        return cls.from_dict(data)


def _known_fields(dc: type, data: dict[str, Any]) -> dict[str, Any]:
    allowed = set(dc.__dataclass_fields__)  # type: ignore[attr-defined]
    unknown = set(data) - allowed
    if unknown:
        raise ConfigError(f"campos desconhecidos em {dc.__name__}: {sorted(unknown)} (permitidos: {sorted(allowed)})")
    return dict(data)
