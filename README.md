# casaradar

Radar pessoal de imóveis em Portugal. Varre vários portais (Imovirtual, Casa Sapo, OLX,
Supercasa e, opcionalmente, Idealista), junta tudo numa base local, aplica **os teus**
filtros, marca anúncios que parecem repetidos entre sites e avisa-te no Telegram quando
aparece algo novo ou quando um preço muda. Cada alerta leva para o anúncio original.

É uma ferramenta de uso pessoal, não um site público: não republica dados de ninguém.

## Como funciona

```
config.yaml ──▶ para cada pesquisa × fonte ──▶ obtém 1-3 páginas de resultados
                                            ──▶ parser da fonte (JSON embebido ▸ HTML ▸ JSON-LD ▸ heurística)
                                            ──▶ filtro local (preço, tipologia, área, palavras a excluir)
                                            ──▶ SQLite (novo? preço mudou? parecido com outro site?)
                                            ──▶ Telegram (ou só consola)
```

- **Filtros são aplicados localmente.** Mesmo que um site ignore um parâmetro do URL, só vês o que bate no config.
- **Primeira execução é silenciosa.** Cria a base com o que já existe e não te inunda com centenas de anúncios antigos.
- **Duplicados entre sites** são marcados ("⚠️ parece já estar em: olx"), nunca escondidos.
- **URL manual.** Se o URL que o radar constrói para um site não funcionar, cola o URL da pesquisa feita no próprio site em `urls:` e o radar trata do resto.

## Instalar

Precisa de Python 3.11+.

```bash
git clone https://github.com/Skisperd/gads casaradar && cd casaradar
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -e .
casaradar init                                        # cria config.yaml e .env
```

Edita `config.yaml` (pesquisas) e `.env` (Telegram). O ficheiro `config.example.yaml` está comentado campo a campo.

## Telegram

1. Fala com o [@BotFather](https://t.me/BotFather), `/newbot`, copia o token para `TELEGRAM_BOT_TOKEN` no `.env`.
2. Abre o teu bot no Telegram e manda-lhe "olá".
3. `casaradar telegram-chat-id` mostra o `chat_id`; copia para `TELEGRAM_CHAT_ID`.
4. `casaradar telegram-test` envia uma mensagem de confirmação.

Sem Telegram configurado o radar funciona na mesma e imprime as novidades na consola.

## Usar

```bash
casaradar run --once            # uma ronda (a primeira só cria a base)
casaradar run --every 30m       # fica a correr e avisa a cada 30 min
casaradar list                  # últimos anúncios guardados
casaradar run --dry-run --search "T2 arrendar Lisboa"   # testar sem guardar nem notificar
```

### Afinar uma fonte

Os portais mudam de layout e de URLs. Quando uma fonte devolve 0 anúncios:

```bash
casaradar debug-fetch olx                 # grava dumps/olx-<data>.html e mostra o que o parser extraiu
casaradar debug-fetch olx --url "https://www.olx.pt/...url-copiado-do-site..."
casaradar parse-file olx dumps/olx-....html   # volta a correr só o parser sobre o HTML gravado
```

Abre o HTML gravado:
- tem anúncios mas o parser extraiu 0 → o seletor/JSON mudou, ajusta em `casaradar/sources/<fonte>.py` (os testes em `tests/` mostram o formato esperado);
- não tem anúncios → o URL está errado (cola o URL certo em `urls:` no config) ou o site bloqueou (403/captcha).

## Correr no GitHub Actions (sem servidor)

O workflow `.github/workflows/radar.yml` corre a cada 30 minutos.

1. Em *Settings → Secrets and variables → Actions* cria `TELEGRAM_BOT_TOKEN` e `TELEGRAM_CHAT_ID`.
2. Faz commit do teu `config.yaml` (não tem segredos).
3. Em *Actions → radar → Run workflow* dispara a primeira execução (cria a base).

A base SQLite é guardada entre execuções com `actions/cache`. Atenção: os IPs dos runners do GitHub
são partilhados e alguns portais bloqueiam-nos; se vires `bloqueado` nos logs, corre em casa
(`casaradar run --every 30m` num Raspberry Pi ou no portátil) ou define `CASARADAR_PROXY` no `.env`.

## Fontes

| fonte | estratégia | estado |
|---|---|---|
| `imovirtual` | JSON `__NEXT_DATA__` da página, fallback HTML | ligado por defeito |
| `casasapo` | HTML (`.property`), fallback JSON-LD e heurística | ligado por defeito |
| `olx` | JSON `__PRERENDERED_STATE__`, fallback HTML (`l-card`) | ligado por defeito |
| `supercasa` | HTML (`.property`), fallback JSON-LD e heurística | ligado por defeito |
| `idealista` | HTML (`article.item`) | experimental: anti-bot agressivo, costuma dar 403 |

Os parsers foram escritos a partir da estrutura conhecida de cada site e testados com fixtures
em `tests/fixtures/`. Na primeira execução real confirma cada fonte com `debug-fetch`.

## Boas práticas

- `request_delay` no config põe uma pausa entre pedidos ao mesmo site. Não o baixes para zero.
- Não corras com intervalos inferiores a ~15 minutos; os portais não publicam assim tão depressa e tu só ganhas bloqueios.
- Isto é para uso pessoal. Republicar os dados num site é outra conversa (direitos de base de dados na UE, termos de uso dos portais).

## Desenvolvimento

```bash
pip install -e ".[dev]"
pytest -q
```

Para acrescentar uma fonte: cria `casaradar/sources/<nome>.py` com uma subclasse de `Source`
(`build_url`, `parse`, opcionalmente `paginate`), regista-a em `casaradar/sources/__init__.py`
e acrescenta uma fixture + teste em `tests/`.
