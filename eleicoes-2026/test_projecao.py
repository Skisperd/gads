"""Testes do parser e do modelo de projeção (python3 -m unittest -v)."""
import unittest

import tse
from mock_tse import MockTSE
from projecao import Unidade, projetar


class TestParser(unittest.TestCase):
    def test_num(self):
        self.assertEqual(tse.num("1.234.567"), 1234567.0)
        self.assertEqual(tse.num("48,43"), 48.43)
        self.assertEqual(tse.num(""), 0.0)
        self.assertEqual(tse.num(None), 0.0)
        self.assertEqual(tse.num(12), 12.0)

    def test_url(self):
        self.assertEqual(
            tse.url("presidente", "br", 1),
            "https://resultados.tse.jus.br/oficial/ele2026/6257/dados-simplificados/br/br-c0001-e006257-r.json")
        self.assertEqual(
            tse.url("governador", "SP", 2, "u"),
            "https://resultados.tse.jus.br/oficial/ele2026/6260/dados/sp/sp-c0003-e006260-u.json")
        self.assertEqual(
            tse.url("senador", "ba", 1),
            "https://resultados.tse.jus.br/oficial/ele2026/6259/dados-simplificados/ba/ba-c0005-e006259-r.json")

    def test_normalizar_simplificado(self):
        raw = {"ele": "6257", "t": "1", "dg": "04/10/2026", "hg": "19:30:00", "s": "1.000", "st": "500", "pst": "50,00",
               "e": "100.000", "ea": "50.000", "c": "40.000", "a": "10.000", "vb": "500", "vn": "1.500", "vv": "38.000", "tv": "40.000",
               "cand": [{"n": "22", "nm": "B", "sqcand": "2", "vap": "18.000", "pvap": "47,37", "e": "n", "st": "", "dvt": "Válido"},
                        {"n": "13", "nm": "A", "sqcand": "1", "vap": "20.000", "pvap": "52,63", "e": "n", "st": "", "dvt": "Válido"}]}
        d = tse.normalizar(raw)
        self.assertEqual(d["secoes_total"], 1000)
        self.assertEqual(d["eleitorado_apurado"], 50000)
        self.assertEqual(d["validos"], 38000)
        self.assertEqual(d["candidatos"][0]["numero"], "13")   # ordenado por votos
        self.assertAlmostEqual(d["candidatos"][0]["pct"], 52.63)
        self.assertFalse(d["final"])

    def test_normalizar_completo(self):
        raw = {"s": {"ts": "1.000", "st": "1.000", "pstn": "100,00"}, "e": {"te": "100.000", "est": "100.000", "c": "80.000", "a": "20.000"},
               "v": {"vv": "76.000", "vb": "1.000", "vn": "3.000", "tv": "80.000"},
               "carg": [{"agr": [{"par": [{"sg": "P1", "cand": [{"n": "13", "nm": "A", "sqcand": "1", "vap": "40.000", "pvapn": "52,63"}]},
                                          {"sg": "P2", "cand": [{"n": "22", "nm": "B", "sqcand": "2", "vap": "36.000", "pvapn": "47,37"}]}]}]}]}
        d = tse.normalizar(raw)
        self.assertEqual(d["validos"], 76000)
        self.assertEqual(d["candidatos"][0]["partido"], "P1")
        self.assertTrue(d["final"])


def _unidade(nome, eleit, frac, votos, comp=0.8, val=0.95):
    ea = eleit * frac
    c = ea * comp
    vv = c * val
    soma = sum(votos.values()) or 1.0
    return Unidade(nome=nome, eleitorado=eleit, eleitorado_apurado=ea, secoes_total=1000, secoes_apuradas=1000 * frac,
                   comparecimento=c, validos=vv, votos={k: vv * v / soma for k, v in votos.items()})


class TestProjecao(unittest.TestCase):
    def test_sem_votos(self):
        r = projetar([_unidade("x", 1000, 0.0, {"13": 0, "22": 0})], ["13", "22"])
        self.assertEqual(r["nivel"], "indefinido")

    def test_matematico_primeiro_turno(self):
        # 99% apurado, 13 com 60%: impossível perder a maioria absoluta
        r = projetar([_unidade("x", 1_000_000, 0.99, {"13": 60, "22": 30, "55": 10})], ["13", "22", "55"])
        self.assertEqual(r["nivel"], "matematico")
        self.assertEqual(r["vencedores"], ["13"])

    def test_matematico_segundo_turno_definido(self):
        r = projetar([_unidade("x", 1_000_000, 0.99, {"13": 45, "22": 40, "55": 15})], ["13", "22", "55"])
        self.assertEqual(r["nivel"], "matematico")
        self.assertEqual(r["segundo_turno"], ["13", "22"])

    def test_indefinido_no_inicio(self):
        r = projetar([_unidade("x", 1_000_000, 0.05, {"13": 45, "22": 40, "55": 15})], ["13", "22", "55"])
        self.assertIn(r["nivel"], ("indefinido",))

    def test_projecao_ponderada_por_uf(self):
        # UF "sul" (rápida) favorece 22; UF "ne" (lenta) favorece 13; eleitorados iguais.
        sul = _unidade("sul", 1_000_000, 0.9, {"13": 35, "22": 60, "55": 5})
        ne = _unidade("ne", 1_000_000, 0.3, {"13": 65, "22": 30, "55": 5})
        r = projetar([sul, ne], ["13", "22", "55"])
        c = {x["numero"]: x for x in r["candidatos"]}
        # soma crua: 22 lidera; projeção ponderada: empate técnico (~50/45) ou 13 à frente
        self.assertGreater(c["22"]["pct_apurado"], c["13"]["pct_apurado"])
        self.assertAlmostEqual(c["13"]["pct_proj"], 50.0, delta=3.0)
        self.assertNotEqual(r["nivel"], "matematico")

    def test_senado_duas_vagas(self):
        r = projetar([_unidade("x", 1_000_000, 0.99, {"111": 40, "122": 35, "133": 20, "144": 5})], ["111", "122", "133", "144"], vagas=2)
        self.assertEqual(r["nivel"], "matematico")
        self.assertEqual(r["vencedores"], ["111", "122"])

    def test_segundo_turno(self):
        r = projetar([_unidade("x", 1_000_000, 0.98, {"13": 52, "22": 48})], ["13", "22"], segundo_turno=True)
        self.assertEqual(r["nivel"], "matematico")
        r = projetar([_unidade("x", 1_000_000, 0.5, {"13": 52, "22": 48})], ["13", "22"], segundo_turno=True)
        self.assertNotEqual(r["nivel"], "matematico")

    def test_convergencia_com_simulador(self):
        """Com a simulação completa, o modelo deve cravar o resultado e nunca contradizê-lo antes."""
        m = MockTSE(turno=1)
        decisoes = []
        for _ in range(40):
            m.avancar()
            unidades = []
            numeros = None
            for uf in tse.UFS + [tse.EXTERIOR]:
                d = tse.normalizar(m.obter("presidente", uf))
                numeros = numeros or [c["numero"] for c in d["candidatos"]]
                unidades.append(Unidade(uf, d["eleitorado"], d["eleitorado_apurado"], d["secoes_total"], d["secoes_apuradas"],
                                        d["comparecimento"], d["validos"], {c["numero"]: c["votos"] for c in d["candidatos"]}))
            r = projetar(unidades, numeros)
            decisoes.append((r["pct_apurado"], r["nivel"], r["vencedores"], r["segundo_turno"]))
            if m.t >= 2.5:
                break
        final = decisoes[-1]
        self.assertEqual(final[1], "matematico")
        # nenhuma projeção/tendência anterior pode contradizer o resultado final
        for pct, nivel, venc, st in decisoes:
            if nivel in ("projecao", "matematico"):
                self.assertEqual((venc, st), (final[2], final[3]), f"projeção contraditória com {pct:.1f}% apurado")


if __name__ == "__main__":
    unittest.main()
