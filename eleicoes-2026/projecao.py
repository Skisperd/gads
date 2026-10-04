"""Modelo de projeção de vencedor a partir da apuração parcial.

Ideia central: a apuração não chega na mesma velocidade em todo lugar (Sul/Sudeste
e cidades pequenas totalizam antes), então a soma crua dos votos apurados é
enviesada. O modelo extrapola unidade por unidade (UF para presidente; a própria
UF para governador/senador), estimando quantos votos válidos cada unidade ainda
vai produzir e qual fatia de cada candidato nesses votos restantes.

Para cada unidade u:
  E_u   = eleitorado_u × comparecimento_u × (válidos/comparecimento)_u   (total esperado de válidos)
  R_u   = max(E_u − válidos_apurados_u, 0)                                (válidos que faltam)
  p_u,c = fatia estimada do candidato c nos votos restantes = média bayesiana entre
          a fatia observada na unidade e a fatia nacional (peso m pseudo-votos)
  proj_c = Σ_u votos_u,c + R_u × p_u,c

Incerteza: δ(g) = 0.04 + 0.30·(1 − g)²  (g = fração já apurada da unidade). A margem
sobre a diferença entre dois candidatos é Σ_u R_u·2δ_u / Σ_u E_u — conservadora
porque supõe todos os erros na mesma direção.

Níveis de resultado (do mais fraco ao mais forte):
  indefinido  → tendencia → projecao → matematico
"matematico" não depende do modelo: usa só os votos já contados e o eleitorado
que ainda não foi apurado (pior caso: todos os votos restantes vão para o rival).
"""
from __future__ import annotations

from dataclasses import dataclass, field

COMPARECIMENTO_PADRAO = 0.79     # 1º turno 2022: ~79%
VALIDOS_PADRAO = 0.955           # válidos / comparecimento (2022: ~95,6%)
PSEUDO_VOTOS = 20000.0           # peso da fatia nacional na média bayesiana por UF
MIN_FRACAO_UNIDADE = 0.02        # abaixo disso a unidade usa a taxa nacional de comparecimento
LIMIAR_TENDENCIA = 0.5           # tendência quando vantagem > 0,5 × margem


def delta(g: float) -> float:
    g = min(max(g, 0.0), 1.0)
    return 0.04 + 0.30 * (1.0 - g) ** 2


@dataclass
class Unidade:
    nome: str
    eleitorado: float
    eleitorado_apurado: float
    secoes_total: float
    secoes_apuradas: float
    comparecimento: float
    validos: float
    votos: dict[str, float] = field(default_factory=dict)   # numero -> votos


@dataclass
class ProjecaoCandidato:
    numero: str
    votos: float
    pct_apurado: float
    votos_proj: float
    pct_proj: float
    margem: float            # ± em pontos percentuais da fatia projetada


def _taxas_nacionais(unidades: list[Unidade]):
    ea = sum(u.eleitorado_apurado for u in unidades)
    comp = sum(u.comparecimento for u in unidades)
    val = sum(u.validos for u in unidades)
    tx_comp = comp / ea if ea > 0 else COMPARECIMENTO_PADRAO
    tx_val = val / comp if comp > 0 else VALIDOS_PADRAO
    # proteção contra valores absurdos no início da apuração
    tx_comp = min(max(tx_comp, 0.55), 0.95)
    tx_val = min(max(tx_val, 0.80), 0.995)
    return tx_comp, tx_val


def projetar(unidades: list[Unidade], numeros: list[str], vagas: int = 1, segundo_turno: bool = False) -> dict:
    """Projeta o resultado de uma disputa.

    unidades: unidades de apuração (UFs para presidente; a UF única para governador/senador)
    numeros: números dos candidatos considerados
    vagas: 1 (majoritário com 2º turno) ou 2 (senado: dois mais votados eleitos)
    segundo_turno: True quando a disputa é entre dois e vence quem tem mais votos
    """
    tx_comp, tx_val = _taxas_nacionais(unidades)
    total_validos = sum(u.validos for u in unidades)
    fatia_nac = {n: (sum(u.votos.get(n, 0.0) for u in unidades) / total_validos if total_validos > 0 else 0.0)
                 for n in numeros}

    E_total = 0.0
    R_total = 0.0
    margem_dif = 0.0           # Σ R_u·2δ_u
    proj = {n: 0.0 for n in numeros}
    apurado = {n: 0.0 for n in numeros}
    restante_max = 0.0         # eleitores que ainda podem votar (pior caso)
    por_unidade = []

    for u in unidades:
        frac_sec = (u.secoes_apuradas / u.secoes_total) if u.secoes_total > 0 else 0.0
        ea = u.eleitorado_apurado if u.eleitorado_apurado > 0 else u.eleitorado * frac_sec
        if ea > MIN_FRACAO_UNIDADE * u.eleitorado and u.comparecimento > 0:
            comp_u = min(max(u.comparecimento / ea, 0.55), 0.95)
        else:
            comp_u = tx_comp
        if u.comparecimento > 0 and frac_sec >= MIN_FRACAO_UNIDADE:
            val_u = min(max(u.validos / u.comparecimento, 0.80), 0.995)
        else:
            val_u = tx_val
        E_u = max(u.eleitorado * comp_u * val_u, u.validos)
        R_u = max(E_u - u.validos, 0.0)
        g_u = (u.validos / E_u) if E_u > 0 else 0.0
        d_u = delta(g_u)
        rest_u = max(u.eleitorado - ea, 0.0)

        E_total += E_u
        R_total += R_u
        margem_dif += R_u * 2.0 * d_u
        restante_max += rest_u

        fatias_u = {}
        for n in numeros:
            v = u.votos.get(n, 0.0)
            p = (v + PSEUDO_VOTOS * fatia_nac[n]) / (u.validos + PSEUDO_VOTOS) if (u.validos + PSEUDO_VOTOS) > 0 else fatia_nac[n]
            fatias_u[n] = p
            proj[n] += v + R_u * p
            apurado[n] += v
        por_unidade.append({
            "nome": u.nome, "pct_secoes": 100.0 * frac_sec, "pct_apurado": 100.0 * g_u,
            "validos": u.validos, "esperado": E_u, "restante": R_u,
            "fatias_proj": {n: 100.0 * ((u.votos.get(n, 0.0) + R_u * fatias_u[n]) / E_u if E_u > 0 else 0.0) for n in numeros},
            "fatias_apuradas": {n: 100.0 * (u.votos.get(n, 0.0) / u.validos if u.validos > 0 else 0.0) for n in numeros},
        })

    margem_pp = 100.0 * (margem_dif / E_total) if E_total > 0 else 100.0   # margem da diferença, em p.p.
    cands = []
    for n in numeros:
        cands.append(ProjecaoCandidato(
            numero=n, votos=apurado[n],
            pct_apurado=100.0 * apurado[n] / total_validos if total_validos > 0 else 0.0,
            votos_proj=proj[n],
            pct_proj=100.0 * proj[n] / E_total if E_total > 0 else 0.0,
            margem=margem_pp / 2.0,
        ))
    cands.sort(key=lambda c: -c.votos_proj)
    g_total = total_validos / E_total if E_total > 0 else 0.0

    resultado = _classificar(cands, total_validos, restante_max, margem_pp, g_total, vagas, segundo_turno)
    resultado.update({
        "pct_apurado": 100.0 * g_total,
        "validos_apurados": total_validos,
        "validos_esperados": E_total,
        "restante_estimado": R_total,
        "eleitores_nao_apurados": restante_max,
        "margem_pp": margem_pp,
        "taxa_comparecimento": tx_comp,
        "taxa_validos": tx_val,
        "candidatos": [c.__dict__ for c in cands],
        "unidades": por_unidade,
    })
    return resultado


def _classificar(cands, validos, restante_max, margem_pp, g_total, vagas, segundo_turno) -> dict:
    """Decide o nível de certeza e a mensagem."""
    if not cands or validos <= 0:
        return {"nivel": "indefinido", "mensagem": "Aguardando os primeiros votos apurados.", "vencedores": [], "segundo_turno": None}

    a = cands[0]
    b = cands[1] if len(cands) > 1 else None
    c3 = cands[2] if len(cands) > 2 else None
    R = restante_max                      # pior caso: todo eleitor não apurado vota válido no rival

    # --- Senado (2 vagas) ou qualquer disputa por N vagas: os N mais votados vencem -----------
    if vagas >= 2:
        eleitos = cands[:vagas]
        corte = cands[vagas] if len(cands) > vagas else None
        if corte is None:
            return {"nivel": "matematico", "mensagem": "Eleitos: " + ", ".join(e.numero for e in eleitos),
                    "vencedores": [e.numero for e in eleitos], "segundo_turno": None}
        ultimo = eleitos[-1]
        if ultimo.votos - corte.votos > R:
            nivel = "matematico"
        elif ultimo.pct_proj - corte.pct_proj > margem_pp:
            nivel = "projecao"
        elif ultimo.pct_proj - corte.pct_proj > LIMIAR_TENDENCIA * margem_pp and g_total > 0.25:
            nivel = "tendencia"
        else:
            nivel = "indefinido"
        return {"nivel": nivel, "mensagem": _msg_vagas(nivel, eleitos), "vencedores": [e.numero for e in eleitos] if nivel != "indefinido" else [],
                "segundo_turno": None}

    # --- 2º turno (ou disputa com 2 candidatos): maioria simples -----------------------------
    if segundo_turno or len(cands) == 2:
        if b is None:
            return {"nivel": "matematico", "mensagem": f"Candidato único: {a.numero}", "vencedores": [a.numero], "segundo_turno": None}
        if a.votos - b.votos > R:
            nivel = "matematico"
        elif a.pct_proj - b.pct_proj > margem_pp:
            nivel = "projecao"
        elif a.pct_proj - b.pct_proj > LIMIAR_TENDENCIA * margem_pp and g_total > 0.25:
            nivel = "tendencia"
        else:
            nivel = "indefinido"
        return {"nivel": nivel, "mensagem": _msg_maioria(nivel, a, b), "vencedores": [a.numero] if nivel != "indefinido" else [],
                "segundo_turno": None}

    # --- 1º turno majoritário: >50% dos válidos vence; senão, os dois primeiros vão ao 2º turno -
    # Matemático: a vence no 1º turno se mesmo que todos os votos restantes sejam válidos e
    # contrários, ainda fica acima de 50%.
    if a.votos > 0.5 * (validos + R):
        return {"nivel": "matematico", "mensagem": f"{a.numero} eleito(a) no 1º turno (matematicamente definido).",
                "vencedores": [a.numero], "segundo_turno": None}
    # Matemático: 2º turno definido se a não consegue chegar a 50% nem com todos os restantes,
    # e b não pode ser alcançado pelo 3º colocado.
    a_nao_vence = (a.votos + R) <= 0.5 * (validos + R)
    b_seguro = b is not None and (c3 is None or b.votos - c3.votos > R)
    if a_nao_vence and b_seguro:
        return {"nivel": "matematico", "mensagem": f"2º turno definido: {a.numero} × {b.numero} (matematicamente).",
                "vencedores": [], "segundo_turno": [a.numero, b.numero]}

    # Projeção estatística
    m = margem_pp
    if a.pct_proj - 50.0 > m / 2.0:
        return {"nivel": "projecao", "mensagem": f"Projeção: {a.numero} eleito(a) no 1º turno.", "vencedores": [a.numero], "segundo_turno": None}
    if b is not None and 50.0 - a.pct_proj > m / 2.0 and (c3 is None or b.pct_proj - c3.pct_proj > m):
        return {"nivel": "projecao", "mensagem": f"Projeção: 2º turno entre {a.numero} e {b.numero}.", "vencedores": [], "segundo_turno": [a.numero, b.numero]}
    if g_total > 0.25:
        if a.pct_proj - 50.0 > LIMIAR_TENDENCIA * m / 2.0:
            return {"nivel": "tendencia", "mensagem": f"Tendência: {a.numero} pode vencer no 1º turno.", "vencedores": [a.numero], "segundo_turno": None}
        if b is not None and 50.0 - a.pct_proj > LIMIAR_TENDENCIA * m / 2.0 and (c3 is None or b.pct_proj - c3.pct_proj > LIMIAR_TENDENCIA * m):
            return {"nivel": "tendencia", "mensagem": f"Tendência: 2º turno entre {a.numero} e {b.numero}.", "vencedores": [], "segundo_turno": [a.numero, b.numero]}
    return {"nivel": "indefinido", "mensagem": "Ainda indefinido: a margem de erro da projeção não permite cravar o resultado.",
            "vencedores": [], "segundo_turno": None}


def _msg_maioria(nivel, a, b):
    if nivel == "matematico":
        return f"{a.numero} eleito(a) (matematicamente definido)."
    if nivel == "projecao":
        return f"Projeção: {a.numero} eleito(a)."
    if nivel == "tendencia":
        return f"Tendência: {a.numero} à frente de {b.numero}."
    return "Ainda indefinido."


def _msg_vagas(nivel, eleitos):
    nomes = ", ".join(e.numero for e in eleitos)
    if nivel == "matematico":
        return f"Eleitos (matematicamente): {nomes}."
    if nivel == "projecao":
        return f"Projeção de eleitos: {nomes}."
    if nivel == "tendencia":
        return f"Tendência: {nomes}."
    return "Ainda indefinido."
