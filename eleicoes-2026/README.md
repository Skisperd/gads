# Apuração e projeção de vencedor — Eleições 2026

Painel local que acompanha a totalização das urnas publicada pelo TSE e projeta o
vencedor (ou o 2º turno) para **Presidente**, **Governadores** (27 UFs) e
**Senadores** (2 vagas por UF). Só precisa de Python 3.9+ — sem dependências.

```bash
cd eleicoes-2026
python3 apuracao.py            # abre o painel em http://localhost:8765
```

Opções:

| flag | efeito |
|---|---|
| `--turno 2` | 2º turno (25/10): presidente e governadores onde houver |
| `--mock` | simulação com dados **fictícios** para testar sem internet |
| `--sem-estaduais` | só presidente (29 arquivos por ciclo em vez de 83) |
| `--intervalo 45` | segundos entre ciclos (o TSE atualiza ~1×/min; não vale descer de 30) |
| `--salvar dados` | grava um snapshot JSON por ciclo (útil para análise posterior) |
| `--porta 8765` | porta do painel |

Endpoints locais: `/` (painel), `/api/estado` (snapshot completo), `/api/historico`
(evolução da apuração e da projeção presidencial, ciclo a ciclo).

## De onde vêm os dados

Arquivos públicos e estáticos do TSE (não é API; é um CDN):

```
https://resultados.tse.jus.br/oficial/ele2026/{eleição}/dados-simplificados/{uf}/{uf}-c{cargo}-e{eleição:06d}-r.json
```

| eleição | o que é |
|---|---|
| 6257 / 6258 | presidente, 1º / 2º turno |
| 6259 / 6260 | governador, senador, deputados — 1º / 2º turno |

Cargos: `0001` presidente, `0003` governador, `0005` senador. UF `br` = Brasil,
`zz` = exterior. O coletor usa ETag (`If-None-Match`), User-Agent de navegador
(o CDN recusa sem) e respeita `429 Retry-After`. Se o arquivo simplificado não
existir, tenta o formato completo (`dados/.../-u.json`).

## Como a projeção funciona (`projecao.py`)

A apuração não chega na mesma velocidade em todo lugar: Sul/Sudeste e cidades
pequenas totalizam antes, e a soma crua dos votos apurados fica enviesada. Por
isso o modelo extrapola **UF por UF** (para presidente) e soma:

1. Para cada UF estima o total de votos válidos que ela vai produzir:
   `eleitorado × comparecimento × (válidos/comparecimento)`, usando as taxas já
   observadas na própria UF (ou as nacionais enquanto a UF tem pouca apuração).
2. A fatia de cada candidato nos votos **que faltam** é a fatia observada na UF,
   puxada levemente para a fatia nacional enquanto a UF tem poucos votos
   (média bayesiana, 20 mil pseudo-votos).
3. `projeção = votos apurados + votos restantes × fatia`.
4. A **margem** cresce com o que falta apurar: `δ(g) = 0,04 + 0,30·(1−g)²` por
   UF (g = fração apurada), somada de forma conservadora (todos os erros na mesma
   direção).

Níveis exibidos no painel:

| nível | significado |
|---|---|
| ✅ **Definido** | matematicamente impossível mudar: mesmo que todos os eleitores ainda não apurados votassem no rival. Não depende do modelo. |
| 📊 **Projeção** | a vantagem supera a margem do modelo. |
| 📈 **Tendência** | vantagem acima de metade da margem, com >25% apurado. |
| ⏳ **Indefinido** | ainda não dá para cravar. |

Para governador e senador a unidade é a própria UF (sem ponderação por município),
então a projeção estadual fica mais conservadora. Quando o TSE marca a
totalização como final, o painel exibe o resultado oficial.

> A projeção é uma estimativa estatística própria; o resultado oficial é sempre o do TSE.

## Testes

```bash
python3 -m unittest -v        # parser dos JSON, modelo e convergência na simulação
python3 apuracao.py --mock    # simulação ponta a ponta no navegador
```

## Arquivos

- `apuracao.py` — coleta em paralelo, monta o snapshot, serve o painel.
- `tse.py` — URLs, download com ETag e normalização dos dois formatos de JSON.
- `projecao.py` — modelo de projeção e classificação do resultado.
- `mock_tse.py` — simulador com números fictícios (só para teste).
- `static/index.html` — painel (vanilla JS, claro/escuro, celular).
