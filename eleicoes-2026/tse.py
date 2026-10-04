"""Acesso aos arquivos públicos de resultados do TSE (Eleições 2026).

O TSE não expõe uma API REST: publica arquivos JSON estáticos em um CDN.
Padrão (formato simplificado, usado aqui como preferência):

  https://resultados.tse.jus.br/oficial/ele2026/{eleicao}/dados-simplificados/{uf}/{uf}-c{cargo}-e{eleicao:06d}-r.json

e o formato completo (usado como reserva se o simplificado não existir):

  https://resultados.tse.jus.br/oficial/ele2026/{eleicao}/dados/{uf}/{uf}-c{cargo}-e{eleicao:06d}-u.json

Códigos de eleição 2026:
  6257 presidente 1º turno   6258 presidente 2º turno
  6259 estaduais 1º turno    6260 estaduais 2º turno
"""
from __future__ import annotations

import json
import re
import time
import urllib.error
import urllib.request

BASE = "https://resultados.tse.jus.br/oficial/ele2026"

CODIGOS = {
    1: {"federal": 6257, "estadual": 6259},
    2: {"federal": 6258, "estadual": 6260},
}

# cargo -> (código do cargo no nome do arquivo, eleição que o contém, nº de vagas)
CARGOS = {
    "presidente": ("0001", "federal", 1),
    "governador": ("0003", "estadual", 1),
    "senador": ("0005", "estadual", 2),
}

UFS = [
    "ac", "al", "am", "ap", "ba", "ce", "df", "es", "go", "ma", "mg", "ms", "mt",
    "pa", "pb", "pe", "pi", "pr", "rj", "rn", "ro", "rr", "rs", "sc", "se", "sp", "to",
]
EXTERIOR = "zz"

HEADERS = {
    # O CDN do TSE recusa requisições sem User-Agent de navegador.
    "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
                  "Chrome/130.0 Safari/537.36",
    "Accept": "application/json, text/plain, */*",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Referer": "https://resultados.tse.jus.br/",
}


def url(cargo: str, uf: str, turno: int = 1, formato: str = "r") -> str:
    ccargo, nivel, _ = CARGOS[cargo]
    eleicao = CODIGOS[turno][nivel]
    pasta = "dados-simplificados" if formato == "r" else "dados"
    uf = uf.lower()
    return f"{BASE}/{eleicao}/{pasta}/{uf}/{uf}-c{ccargo}-e{eleicao:06d}-{formato}.json"


def num(valor) -> float:
    """Converte números no formato pt-BR ("1.234.567", "48,43", "") para float."""
    if valor is None:
        return 0.0
    if isinstance(valor, (int, float)):
        return float(valor)
    s = str(valor).strip()
    if not s or s in {"-", "—"}:
        return 0.0
    s = s.replace(".", "").replace(",", ".")
    try:
        return float(s)
    except ValueError:
        m = re.search(r"-?\d+(?:\.\d+)?", s)
        return float(m.group()) if m else 0.0


def _primeiro(d: dict, *chaves, default=None):
    for k in chaves:
        if isinstance(d, dict) and k in d and d[k] not in (None, ""):
            return d[k]
    return default


def normalizar(raw: dict) -> dict:
    """Converte o JSON bruto do TSE (simplificado ou completo) para um dicionário uniforme.

    Saída:
      secoes_total, secoes_apuradas, pct_secoes,
      eleitorado, eleitorado_apurado, comparecimento, abstencao,
      validos, brancos, nulos, total_votos,
      atualizado (texto), final (bool),
      candidatos: [{numero, nome, sq, votos, pct, situacao, partido}]
    """
    if "cand" in raw and isinstance(raw.get("cand"), list):
        return _normalizar_simplificado(raw)
    if "carg" in raw:
        return _normalizar_completo(raw)
    raise ValueError("JSON do TSE em formato desconhecido")


def _normalizar_simplificado(raw: dict) -> dict:
    sec_total = num(raw.get("s"))
    sec_apur = num(raw.get("st"))
    pct_sec = num(raw.get("pst"))
    if pct_sec == 0 and sec_total > 0:
        pct_sec = 100.0 * sec_apur / sec_total
    eleitorado = num(raw.get("e"))
    eleit_apur = num(_primeiro(raw, "ea", "esi"))
    if eleit_apur == 0 and eleitorado > 0 and sec_total > 0:
        eleit_apur = eleitorado * sec_apur / sec_total
    comp = num(raw.get("c"))
    abst = num(raw.get("a"))
    validos = num(raw.get("vv"))
    brancos = num(raw.get("vb"))
    nulos = num(raw.get("vn"))
    total = num(raw.get("tv")) or (validos + brancos + nulos)
    if comp == 0:
        comp = total
    cands = []
    for c in raw.get("cand", []):
        cands.append({
            "numero": str(c.get("n", "")).strip(),
            "nome": str(c.get("nm", "")).strip(),
            "sq": str(c.get("sqcand", "")).strip(),
            "votos": num(c.get("vap")),
            "pct": num(c.get("pvap")),
            "situacao": str(_primeiro(c, "st", "dvt", default="") or "").strip(),
            "eleito": str(c.get("e", "")).strip().lower() == "s",
            "partido": str(_primeiro(c, "sg", "par", default="") or "").strip(),
        })
    atualizado = f"{raw.get('dg', '')} {raw.get('hg', '')}".strip()
    final = pct_sec >= 100.0 or str(raw.get("f", "")).lower().startswith("f")
    return {
        "secoes_total": sec_total, "secoes_apuradas": sec_apur, "pct_secoes": pct_sec,
        "eleitorado": eleitorado, "eleitorado_apurado": eleit_apur,
        "comparecimento": comp, "abstencao": abst,
        "validos": validos, "brancos": brancos, "nulos": nulos, "total_votos": total,
        "atualizado": atualizado, "final": final, "candidatos": _ordenar(cands),
    }


def _normalizar_completo(raw: dict) -> dict:
    s = raw.get("s") or {}
    e = raw.get("e") or {}
    v = raw.get("v") or {}
    sec_total = num(_primeiro(s, "ts", "s"))
    sec_apur = num(_primeiro(s, "st"))
    pct_sec = num(_primeiro(s, "pstn", "pst"))
    if pct_sec == 0 and sec_total > 0:
        pct_sec = 100.0 * sec_apur / sec_total
    eleitorado = num(_primeiro(e, "te", "e"))
    eleit_apur = num(_primeiro(e, "est", "ea"))
    if eleit_apur == 0 and eleitorado > 0 and sec_total > 0:
        eleit_apur = eleitorado * sec_apur / sec_total
    comp = num(_primeiro(e, "c", "cp", "comp"))
    abst = num(_primeiro(e, "a", "ab", "abst"))
    validos = num(_primeiro(v, "vv"))
    brancos = num(_primeiro(v, "vb"))
    nulos = num(_primeiro(v, "vn", "vnt"))
    total = num(_primeiro(v, "tv")) or (validos + brancos + nulos)
    if comp == 0:
        comp = total
    cands = []
    for carg in raw.get("carg", [])[:1]:
        for agr in carg.get("agr", []):
            for par in agr.get("par", []):
                sigla = str(_primeiro(par, "sg", "nm", default="") or "")
                for c in par.get("cand", []):
                    numero = str(c.get("n", "")).strip()
                    if not numero:
                        continue
                    cands.append({
                        "numero": numero,
                        "nome": str(c.get("nm", "")).strip(),
                        "sq": str(c.get("sqcand", "")).strip(),
                        "votos": num(c.get("vap")),
                        "pct": num(_primeiro(c, "pvapn", "pvap")),
                        "situacao": str(_primeiro(c, "st", "dvt", default="") or "").strip(),
                        "eleito": str(c.get("e", "")).strip().lower() == "s",
                        "partido": sigla,
                    })
    atualizado = f"{raw.get('dg', '')} {raw.get('hg', '')}".strip()
    final = pct_sec >= 100.0
    return {
        "secoes_total": sec_total, "secoes_apuradas": sec_apur, "pct_secoes": pct_sec,
        "eleitorado": eleitorado, "eleitorado_apurado": eleit_apur,
        "comparecimento": comp, "abstencao": abst,
        "validos": validos, "brancos": brancos, "nulos": nulos, "total_votos": total,
        "atualizado": atualizado, "final": final, "candidatos": _ordenar(cands),
    }


def _ordenar(cands):
    return sorted(cands, key=lambda c: (-c["votos"], c["numero"]))


class ClienteTSE:
    """Baixa arquivos do TSE com revalidação por ETag e respeito a 429/Retry-After."""

    def __init__(self, turno: int = 1, timeout: float = 20.0):
        self.turno = turno
        self.timeout = timeout
        self._cache: dict[str, tuple[str | None, dict]] = {}   # url -> (etag, json)
        self._pausado_ate = 0.0
        self.erros: dict[str, str] = {}

    def obter(self, cargo: str, uf: str):
        """Retorna o JSON bruto (dict) ou None se indisponível."""
        for formato in ("r", "u"):
            u = url(cargo, uf, self.turno, formato)
            dados = self._baixar(u)
            if dados is not None:
                return dados
            # alguns arquivos são publicados com a UF em maiúsculas
            u2 = u.replace(f"/{uf.lower()}/{uf.lower()}-", f"/{uf.upper()}/{uf.upper()}-")
            if u2 != u:
                dados = self._baixar(u2)
                if dados is not None:
                    return dados
        return None

    def _baixar(self, u: str):
        if time.time() < self._pausado_ate:
            etag, cached = self._cache.get(u, (None, None))
            return cached
        headers = dict(HEADERS)
        etag, cached = self._cache.get(u, (None, None))
        if etag:
            headers["If-None-Match"] = etag
        req = urllib.request.Request(u, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                corpo = resp.read()
                novo_etag = resp.headers.get("ETag")
                dados = json.loads(corpo.decode("utf-8", errors="replace"))
                self._cache[u] = (novo_etag, dados)
                self.erros.pop(u, None)
                return dados
        except urllib.error.HTTPError as e:
            if e.code == 304 and cached is not None:
                return cached
            if e.code == 429:
                espera = num(e.headers.get("Retry-After")) or 30
                self._pausado_ate = time.time() + espera
                self.erros[u] = f"429 (aguardando {espera:.0f}s)"
                return cached
            if e.code == 404:
                return None
            self.erros[u] = f"HTTP {e.code}"
            return cached
        except Exception as e:  # rede, timeout, JSON inválido
            self.erros[u] = str(e)[:120]
            return cached
