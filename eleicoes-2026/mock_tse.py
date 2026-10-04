"""Simulador de apuração no formato dos arquivos do TSE — SOMENTE PARA TESTES.

Gera números FICTÍCIOS para validar coleta, modelo e painel sem acesso ao TSE.
Nada aqui representa resultado real. A apuração simulada avança a cada chamada
de `avancar()`; UFs do Sul/Sudeste totalizam mais rápido, como costuma ocorrer.
"""
from __future__ import annotations

import random

from tse import UFS, EXTERIOR

# Eleitorado aproximado por UF (ordem de grandeza de 2022) — só para a simulação.
ELEITORADO = {
    "sp": 34_667_000, "mg": 16_290_000, "rj": 12_787_000, "ba": 11_300_000, "rs": 8_600_000,
    "pr": 8_620_000, "pe": 7_000_000, "ce": 6_900_000, "pa": 6_100_000, "sc": 5_500_000,
    "ma": 5_000_000, "go": 5_000_000, "pb": 3_000_000, "es": 2_900_000, "am": 2_600_000,
    "pi": 2_600_000, "rn": 2_500_000, "mt": 2_500_000, "al": 2_200_000, "df": 2_200_000,
    "ms": 1_900_000, "se": 1_700_000, "ro": 1_200_000, "to": 1_100_000, "ac": 600_000,
    "ap": 530_000, "rr": 350_000, "zz": 700_000,
}
VELOCIDADE = {  # fator de velocidade de totalização por UF
    "rs": 1.6, "sc": 1.6, "pr": 1.5, "sp": 1.2, "mg": 1.1, "rj": 1.1, "es": 1.3, "ms": 1.3, "mt": 1.2,
    "go": 1.2, "df": 1.5, "to": 1.1, "ba": 0.8, "pe": 0.85, "ce": 0.85, "ma": 0.75, "pa": 0.7,
    "am": 0.7, "pi": 0.8, "pb": 0.9, "rn": 0.9, "al": 0.9, "se": 0.9, "ac": 0.8, "ap": 0.7,
    "rr": 0.8, "ro": 0.9, "zz": 0.5,
}
NORDESTE = {"ba", "pe", "ce", "ma", "pi", "pb", "rn", "al", "se"}
SUL = {"rs", "sc", "pr"}

PRESIDENCIAIS = [  # números reais dos candidatos de 2026; fatias são INVENTADAS
    ("13", "CANDIDATO 13", 0.44), ("22", "CANDIDATO 22", 0.36), ("55", "CANDIDATO 55", 0.07),
    ("30", "CANDIDATO 30", 0.05), ("14", "CANDIDATO 14", 0.03), ("70", "CANDIDATO 70", 0.02),
    ("16", "CANDIDATO 16", 0.006), ("21", "CANDIDATO 21", 0.006), ("27", "CANDIDATO 27", 0.006),
    ("29", "CANDIDATO 29", 0.006), ("35", "CANDIDATO 35", 0.006), ("80", "CANDIDATO 80", 0.006),
]


def _fmt_int(v: float) -> str:
    return f"{int(round(v)):,}".replace(",", ".")


def _fmt_pct(v: float) -> str:
    return f"{v:.2f}".replace(".", ",")


class MockTSE:
    def __init__(self, turno: int = 1, passo: float = 0.06, seed: int = 2026):
        self.turno = turno
        self.passo = passo
        self.t = 0.0
        self.rng = random.Random(seed)
        self.erros: dict[str, str] = {}
        self._disputas: dict[tuple, list] = {}
        self._ruido: dict[tuple, float] = {}

    def avancar(self):
        self.t = min(self.t + self.passo, 2.5)  # além de 1.0 para as UFs lentas completarem

    # ---------------------------------------------------------------------------------
    def _candidatos(self, cargo: str, uf: str):
        chave = (cargo, uf)
        if chave in self._disputas:
            return self._disputas[chave]
        if cargo == "presidente":
            cands = []
            for n, nm, base in PRESIDENCIAIS:
                fator = 1.0
                if n == "13":
                    fator = 1.45 if uf in NORDESTE else (0.75 if uf in SUL else 0.95)
                elif n == "22":
                    fator = 0.6 if uf in NORDESTE else (1.35 if uf in SUL else 1.05)
                cands.append([n, nm, base * fator])
            if self.turno == 2:
                cands = [c for c in cands if c[0] in ("13", "22")]
        elif cargo == "governador":
            k = 2 if self.turno == 2 else 4
            pesos = [self.rng.uniform(0.2, 1.0) for _ in range(k)]
            cands = [[f"{10 + 5 * i + 0}", f"GOV {uf.upper()} {i + 1}", pesos[i]] for i in range(k)]
        else:  # senador — 2 vagas
            pesos = [self.rng.uniform(0.2, 1.0) for _ in range(5)]
            cands = [[f"{100 + 11 * i}", f"SEN {uf.upper()} {i + 1}", pesos[i]] for i in range(5)]
        soma = sum(c[2] for c in cands)
        for c in cands:
            c[2] /= soma
        self._disputas[chave] = cands
        return cands

    def obter(self, cargo: str, uf: str):
        uf = uf.lower()
        if cargo != "presidente" and uf in ("br", EXTERIOR):
            return None
        if cargo == "governador" and self.turno == 2 and uf not in ("sp", "rj", "mg"):
            return None  # só algumas UFs têm 2º turno
        if uf == "br":
            return self._agregado(cargo)
        return self._arquivo(cargo, uf)

    def _arquivo(self, cargo: str, uf: str):
        eleit = ELEITORADO[uf]
        secoes = max(int(eleit / 330), 50)
        frac = min(VELOCIDADE[uf] * self.t, 1.0)
        # início: seções pequenas do interior, pró-candidato 22 em todo lugar (viés inicial)
        vies = 0.08 * (1.0 - frac)
        sec_apur = int(secoes * frac)
        ea = eleit * frac
        comp_tx = 0.80 - 0.03 * (uf in NORDESTE)
        comp = ea * comp_tx
        validos = comp * 0.955
        cands = self._candidatos(cargo, uf)
        fatias = []
        for n, nm, p in cands:
            r = self._ruido.setdefault((cargo, uf, n), self.rng.uniform(-0.03, 0.03))
            q = p + r
            if cargo == "presidente":
                q += vies if n == "22" else (-vies if n == "13" else 0)
            fatias.append(max(q, 0.001))
        soma = sum(fatias)
        fatias = [f / soma for f in fatias]
        cand_json = []
        for (n, nm, _), f in zip(cands, fatias):
            cand_json.append({"seq": "1", "sqcand": "999" + n, "n": n, "nm": nm,
                              "vap": _fmt_int(validos * f), "pvap": _fmt_pct(100 * f), "e": "n", "st": "", "dvt": "Válido"})
        cand_json.sort(key=lambda c: -float(c["vap"].replace(".", "")))
        return {
            "ele": "6257", "t": str(self.turno), "f": "Parcial" if frac < 1 else "Final",
            "dg": "04/10/2026", "hg": f"{(17 + int(4 * self.t)) % 24:02d}:{int(60 * ((4 * self.t) % 1)):02d}:00",
            "cdabr": uf.upper(), "s": _fmt_int(secoes), "st": _fmt_int(sec_apur), "pst": _fmt_pct(100 * frac),
            "e": _fmt_int(eleit), "ea": _fmt_int(ea), "c": _fmt_int(comp), "a": _fmt_int(ea - comp),
            "vb": _fmt_int(comp * 0.015), "vn": _fmt_int(comp * 0.03), "vv": _fmt_int(validos), "tv": _fmt_int(comp),
            "cand": cand_json,
        }

    def _agregado(self, cargo: str):
        from tse import num
        total = {"s": 0, "st": 0, "e": 0, "ea": 0, "c": 0, "a": 0, "vb": 0, "vn": 0, "vv": 0, "tv": 0}
        votos: dict[str, float] = {}
        nomes = {}
        for uf in UFS + [EXTERIOR]:
            a = self._arquivo(cargo, uf)
            for k in total:
                total[k] += num(a[k])
            for c in a["cand"]:
                votos[c["n"]] = votos.get(c["n"], 0) + num(c["vap"])
                nomes[c["n"]] = c["nm"]
        cand_json = [{"seq": "1", "sqcand": "999" + n, "n": n, "nm": nomes[n], "vap": _fmt_int(v),
                      "pvap": _fmt_pct(100 * v / total["vv"] if total["vv"] else 0), "e": "n", "st": "", "dvt": "Válido"}
                     for n, v in sorted(votos.items(), key=lambda kv: -kv[1])]
        pst = 100 * total["st"] / total["s"] if total["s"] else 0
        return {"ele": "6257", "t": str(self.turno), "f": "Parcial" if pst < 100 else "Final",
                "dg": "04/10/2026", "hg": "20:00:00", "cdabr": "BR",
                **{k: _fmt_int(v) for k, v in total.items()}, "pst": _fmt_pct(pst), "cand": cand_json}
