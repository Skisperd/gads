#!/usr/bin/env python3
"""Painel de apuração e projeção de vencedor — Eleições 2026.

Uso:
  python3 apuracao.py                 # 1º turno, dados do TSE, painel em http://localhost:8765
  python3 apuracao.py --turno 2       # 2º turno (25/10)
  python3 apuracao.py --mock          # simulação com dados FICTÍCIOS (sem internet)
  python3 apuracao.py --sem-estaduais # só presidente (menos requisições)
  python3 apuracao.py --salvar dados  # grava um snapshot JSON por ciclo nessa pasta

Só usa a biblioteca padrão do Python (3.9+).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

import tse
from projecao import Unidade, projetar

AQUI = os.path.dirname(os.path.abspath(__file__))
BRASILIA = timezone(timedelta(hours=-3))

ESTADO: dict = {"pronto": False, "mensagem": "Iniciando coleta..."}
HISTORICO: list[dict] = []
TRAVA = threading.Lock()


# ----------------------------------------------------------------------------------- coleta
def _unidade(nome: str, d: dict) -> Unidade:
    return Unidade(
        nome=nome, eleitorado=d["eleitorado"], eleitorado_apurado=d["eleitorado_apurado"],
        secoes_total=d["secoes_total"], secoes_apuradas=d["secoes_apuradas"],
        comparecimento=d["comparecimento"], validos=d["validos"],
        votos={c["numero"]: c["votos"] for c in d["candidatos"]},
    )


def _info_candidatos(docs: list[dict]) -> dict:
    """numero -> {nome, partido, sq, situacao} a partir de qualquer arquivo disponível."""
    info = {}
    for d in docs:
        for c in d["candidatos"]:
            atual = info.setdefault(c["numero"], {"nome": c["nome"], "partido": c["partido"], "sq": c["sq"], "situacao": "", "eleito": False})
            if c["situacao"] and c["situacao"].lower() not in ("válido", "valido"):
                atual["situacao"] = c["situacao"]
            atual["eleito"] = atual["eleito"] or c["eleito"]
    return info


def _montar_disputa(docs_por_unidade: dict[str, dict], vagas: int, segundo_turno: bool, nacional: dict | None = None) -> dict:
    docs = [d for d in docs_por_unidade.values() if d]
    if not docs:
        return {"disponivel": False}
    info = _info_candidatos(docs + ([nacional] if nacional else []))
    numeros = list(info.keys())
    unidades = [_unidade(nome, d) for nome, d in docs_por_unidade.items() if d]
    proj = projetar(unidades, numeros, vagas=vagas, segundo_turno=segundo_turno)
    for c in proj["candidatos"]:
        c.update(info.get(c["numero"], {}))
    # totais oficiais (do arquivo nacional, quando existir; senão soma das unidades)
    base = nacional or {
        "secoes_total": sum(d["secoes_total"] for d in docs), "secoes_apuradas": sum(d["secoes_apuradas"] for d in docs),
        "eleitorado": sum(d["eleitorado"] for d in docs), "comparecimento": sum(d["comparecimento"] for d in docs),
        "validos": sum(d["validos"] for d in docs), "brancos": sum(d["brancos"] for d in docs), "nulos": sum(d["nulos"] for d in docs),
        "atualizado": max((d["atualizado"] for d in docs), default=""), "final": all(d["final"] for d in docs),
    }
    pct_sec = 100.0 * base["secoes_apuradas"] / base["secoes_total"] if base["secoes_total"] else 0.0
    proj.update({
        "disponivel": True,
        "secoes_total": base["secoes_total"], "secoes_apuradas": base["secoes_apuradas"], "pct_secoes": pct_sec,
        "eleitorado": base["eleitorado"], "comparecimento": base["comparecimento"],
        "validos": base["validos"], "brancos": base["brancos"], "nulos": base["nulos"],
        "atualizado": base["atualizado"], "final": base["final"],
    })
    if base["final"]:
        proj["nivel"] = "matematico"
        proj["mensagem"] = "Totalização final do TSE: " + proj["mensagem"]
    return proj


def coletar(cliente, turno: int, estaduais: bool, ciclo: int, modo: str) -> dict:
    """Baixa todos os arquivos de um ciclo e monta o snapshot."""
    pedidos = [("presidente", "br")] + [("presidente", uf) for uf in tse.UFS + [tse.EXTERIOR]]
    if estaduais:
        pedidos += [("governador", uf) for uf in tse.UFS] + [("senador", uf) for uf in tse.UFS]
    brutos: dict[tuple, dict | None] = {}

    def baixar(p):
        try:
            raw = cliente.obter(*p)
            return p, (tse.normalizar(raw) if raw else None)
        except Exception as e:  # arquivo inesperado: não derruba o ciclo
            cliente.erros[str(p)] = f"parse: {e}"[:120]
            return p, None

    with ThreadPoolExecutor(max_workers=8) as pool:
        for p, d in pool.map(baixar, pedidos):
            brutos[p] = d

    segundo = turno == 2
    pres_uf = {uf: brutos.get(("presidente", uf)) for uf in tse.UFS + [tse.EXTERIOR]}
    presidente = _montar_disputa(pres_uf, vagas=1, segundo_turno=segundo, nacional=brutos.get(("presidente", "br")))

    governadores, senadores = {}, {}
    if estaduais:
        for uf in tse.UFS:
            g = brutos.get(("governador", uf))
            if g:
                governadores[uf] = _montar_disputa({uf: g}, vagas=1, segundo_turno=segundo)
            s = brutos.get(("senador", uf))
            if s and not segundo:
                senadores[uf] = _montar_disputa({uf: s}, vagas=2, segundo_turno=False)

    agora = datetime.now(BRASILIA)
    return {
        "pronto": True, "modo": modo, "turno": turno, "ciclo": ciclo,
        "gerado_em": agora.strftime("%d/%m/%Y %H:%M:%S") + " (Brasília)",
        "erros": dict(list(cliente.erros.items())[:20]),
        "presidente": presidente, "governadores": governadores, "senadores": senadores,
    }


def laco_coleta(cliente, turno: int, intervalo: float, estaduais: bool, modo: str, salvar: str | None):
    ciclo = 0
    while True:
        inicio = time.time()
        ciclo += 1
        try:
            if hasattr(cliente, "avancar"):
                cliente.avancar()
            snap = coletar(cliente, turno, estaduais, ciclo, modo)
            with TRAVA:
                ESTADO.clear()
                ESTADO.update(snap)
                p = snap["presidente"]
                if p.get("disponivel"):
                    HISTORICO.append({
                        "t": snap["gerado_em"], "pct_apurado": p["pct_apurado"], "pct_secoes": p["pct_secoes"],
                        "nivel": p["nivel"], "mensagem": p["mensagem"],
                        "candidatos": {c["numero"]: [round(c["pct_apurado"], 2), round(c["pct_proj"], 2)] for c in p["candidatos"][:6]},
                    })
                    del HISTORICO[:-2000]
            if salvar:
                os.makedirs(salvar, exist_ok=True)
                nome = os.path.join(salvar, datetime.now(BRASILIA).strftime("%Y%m%d-%H%M%S") + ".json")
                with open(nome, "w", encoding="utf-8") as f:
                    json.dump(snap, f, ensure_ascii=False)
            p = snap["presidente"]
            if p.get("disponivel"):
                print(f"[{snap['gerado_em']}] ciclo {ciclo}: {p['pct_secoes']:.1f}% das seções, "
                      f"{p['pct_apurado']:.1f}% dos votos estimados — {p['nivel']}: {p['mensagem']}", flush=True)
            else:
                print(f"[{snap['gerado_em']}] ciclo {ciclo}: nenhum arquivo do TSE disponível ainda "
                      f"({len(cliente.erros)} erros)", flush=True)
            if p.get("final") and modo == "simulacao":
                print("Simulação concluída.", flush=True)
        except Exception as e:
            print(f"erro no ciclo {ciclo}: {e}", file=sys.stderr, flush=True)
            with TRAVA:
                ESTADO["mensagem"] = f"erro no ciclo {ciclo}: {e}"
        time.sleep(max(intervalo - (time.time() - inicio), 2.0))


# ----------------------------------------------------------------------------------- servidor
class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):  # silencia o log por requisição
        pass

    def _json(self, obj, status=200):
        corpo = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(corpo)))
        self.end_headers()
        self.wfile.write(corpo)

    def do_GET(self):
        caminho = urlparse(self.path).path
        if caminho == "/api/estado":
            with TRAVA:
                return self._json(ESTADO)
        if caminho == "/api/historico":
            with TRAVA:
                return self._json(HISTORICO)
        if caminho in ("/", "/index.html"):
            try:
                with open(os.path.join(AQUI, "static", "index.html"), "rb") as f:
                    corpo = f.read()
            except FileNotFoundError:
                return self._json({"erro": "static/index.html não encontrado"}, 500)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(corpo)))
            self.end_headers()
            self.wfile.write(corpo)
            return
        self._json({"erro": "não encontrado"}, 404)


def main():
    ap = argparse.ArgumentParser(description="Apuração e projeção — Eleições 2026")
    ap.add_argument("--turno", type=int, choices=(1, 2), default=1)
    ap.add_argument("--porta", type=int, default=8765)
    ap.add_argument("--intervalo", type=float, default=45.0, help="segundos entre ciclos de coleta (TSE atualiza ~1/min)")
    ap.add_argument("--mock", action="store_true", help="simulação com dados fictícios, sem acessar o TSE")
    ap.add_argument("--sem-estaduais", action="store_true", help="não coletar governador/senador")
    ap.add_argument("--salvar", metavar="PASTA", help="gravar um snapshot JSON por ciclo")
    args = ap.parse_args()

    if args.mock:
        from mock_tse import MockTSE
        cliente = MockTSE(turno=args.turno)
        modo = "simulacao"
        if args.intervalo == 45.0:
            args.intervalo = 5.0
    else:
        cliente = tse.ClienteTSE(turno=args.turno)
        modo = "tse"

    th = threading.Thread(target=laco_coleta, args=(cliente, args.turno, args.intervalo, not args.sem_estaduais, modo, args.salvar), daemon=True)
    th.start()

    srv = ThreadingHTTPServer(("0.0.0.0", args.porta), Handler)
    print(f"Painel: http://localhost:{args.porta}  (modo: {modo}, turno {args.turno}, intervalo {args.intervalo:.0f}s)", flush=True)
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
