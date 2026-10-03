"""Registo das fontes disponíveis."""

from __future__ import annotations

from .base import Source
from .casasapo import CasaSapoSource
from .idealista import IdealistaSource
from .imovirtual import ImovirtualSource
from .olx import OlxSource
from .supercasa import SupercasaSource

SOURCES: dict[str, type[Source]] = {
    ImovirtualSource.name: ImovirtualSource,
    CasaSapoSource.name: CasaSapoSource,
    OlxSource.name: OlxSource,
    SupercasaSource.name: SupercasaSource,
    IdealistaSource.name: IdealistaSource,
}


def get_source(name: str) -> Source:
    try:
        return SOURCES[name.lower()]()
    except KeyError as exc:
        raise KeyError(f"fonte desconhecida '{name}'. Disponíveis: {', '.join(SOURCES)}") from exc
