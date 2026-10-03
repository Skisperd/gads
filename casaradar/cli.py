"""Linha de comandos: casaradar run | list | debug-fetch | init | telegram-test | telegram-chat-id."""

from __future__ import annotations

import argparse
import json
import logging
import os
import re
import shutil
import sys
import time
from datetime import datetime
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler
from rich.table import Table

from . import __version__
from .config import Config, ConfigError
from .engine import run_once
from .http import Fetcher
from .notify import TelegramNotifier, print_events
from .sources import SOURCES, get_source
from .storage import Storage

console = Console()
EXAMPLE_CONFIG = Path(__file__).resolve().parent.parent / "config.example.yaml"


def _load_env(path: str = ".env") -> None:
    """Carrega um .env simples (KEY=VALUE) sem dependências."""
    p = Path(path)
    if not p.exists():
        return
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def _parse_interval(text: str) -> int:
    m = re.fullmatch(r"(\d+)\s*([smh]?)", text.strip().lower())
    if not m:
        raise argparse.ArgumentTypeError("intervalo inválido; use por ex. 30m, 2h, 900s")
    n, unit = int(m.group(1)), m.group(2) or "s"
    return n * {"s": 1, "m": 60, "h": 3600}[unit]


def _config(args) -> Config:
    try:
        return Config.load(args.config)
    except ConfigError as exc:
        console.print(f"[red]Erro de configuração:[/red] {exc}")
        sys.exit(2)


def cmd_init(args) -> int:
    dest = Path(args.config)
    if dest.exists() and not args.force:
        console.print(f"{dest} já existe (use --force para substituir).")
        return 1
    shutil.copy(EXAMPLE_CONFIG, dest)
    if not Path(".env").exists() and (EXAMPLE_CONFIG.parent / ".env.example").exists():
        shutil.copy(EXAMPLE_CONFIG.parent / ".env.example", ".env")
        console.print("Criado .env a partir de .env.example — preencha o token e o chat_id do Telegram.")
    console.print(f"Criado {dest}. Edite as pesquisas e corra: [bold]casaradar run --once[/bold]")
    return 0


def cmd_run(args) -> int:
    cfg = _config(args)
    storage = Storage(cfg.storage)
    notifier = TelegramNotifier(cfg.telegram)
    notify = not args.no_notify and not args.dry_run
    if notify and not notifier.ready:
        console.print("[yellow]Telegram não configurado (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID). Só vou imprimir na consola.[/yellow]")
        notify = False

    def one_round() -> None:
        started = time.monotonic()
        events, stats = run_once(cfg, storage, only_search=args.search, only_source=args.source, first_run_quiet=None if not args.notify_first_run else False)
        print_events(events, console)
        srcs = ", ".join(f"{k}={v}" for k, v in stats.per_source.items()) or "nada obtido"
        console.print(f"[dim]{datetime.now():%H:%M:%S} · obtidos {stats.fetched} ({srcs}) · passaram no filtro {stats.matched} · novos {stats.new} · preços alterados {stats.price_changes} · {time.monotonic() - started:.0f}s[/dim]")
        for err in stats.errors:
            console.print(f"[red]erro:[/red] {err}")
        if stats.fetched == 0 and not stats.errors:
            console.print("[yellow]Nenhuma fonte devolveu anúncios. Corra 'casaradar debug-fetch <fonte>' para ver o HTML e ajustar o URL em 'urls:'.[/yellow]")
        if notify and events:
            try:
                notifier.send_events(events)
                storage.mark_notified([e.listing.key for e in events])
                console.print(f"[green]Enviadas {len(events)} notificações no Telegram.[/green]")
            except Exception as exc:  # noqa: BLE001
                console.print(f"[red]Falha ao notificar no Telegram:[/red] {exc}")

    if args.dry_run:
        console.print("[dim]dry-run: nada será guardado nem notificado.[/dim]")
        storage.close()
        storage = Storage(":memory:")
    try:
        if args.every is None or args.once:
            one_round()
            return 0
        console.print(f"A correr a cada {args.every}s. Ctrl+C para sair.")
        while True:
            one_round()
            time.sleep(args.every)
    except KeyboardInterrupt:
        console.print("\nAté já.")
        return 0
    finally:
        storage.close()


def cmd_list(args) -> int:
    cfg = _config(args)
    storage = Storage(cfg.storage)
    rows = storage.recent(args.search, args.limit)
    if not rows:
        console.print("Base de dados vazia. Corra 'casaradar run --once' primeiro.")
        return 0
    table = Table(title=f"Últimos {len(rows)} anúncios ({storage.count()} no total)")
    for col in ("visto", "pesquisa", "fonte", "preço", "tip.", "m²", "local", "título"):
        table.add_column(col, justify="right" if col in ("preço", "m²") else "left")
    for r in rows:
        price = f"{r['price']:,}".replace(",", " ") if r["price"] is not None else "?"
        table.add_row(
            r["first_seen"][5:16].replace("T", " "), r["search_name"], r["source"], price, r["typology"] or "",
            f"{int(r['area_m2'])}" if r["area_m2"] else "", (r["location"] or "")[:28], f"[link={r['url']}]{(r['title'] or '')[:60]}[/link]",
        )
    console.print(table)
    storage.close()
    return 0


def cmd_debug_fetch(args) -> int:
    """Obtém a primeira página de uma fonte, grava o HTML em disco e mostra o que o parser extraiu."""
    cfg = _config(args)
    search = next((s for s in cfg.searches if s.name == args.search), None) if args.search else cfg.searches[0]
    if search is None:
        console.print(f"[red]pesquisa '{args.search}' não existe no config[/red]")
        return 2
    source = get_source(args.source_name)
    url = args.url or source.start_url(search)
    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    console.print(f"URL: {url}")
    fetcher = Fetcher(delay=0, timeout=cfg.timeout, user_agent=cfg.user_agent)
    try:
        html = fetcher.get(url)
    except Exception as exc:  # noqa: BLE001
        console.print(f"[red]falha:[/red] {exc}")
        return 1
    finally:
        fetcher.close()
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    html_path = out_dir / f"{source.name}-{stamp}.html"
    html_path.write_text(html, encoding="utf-8")
    listings = source.parse(html, search, url)
    json_path = out_dir / f"{source.name}-{stamp}.json"
    json_path.write_text(json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=2), encoding="utf-8")
    console.print(f"HTML guardado em {html_path} ({len(html)} bytes); {len(listings)} anúncios extraídos -> {json_path}")
    for l in listings[: args.show]:
        console.print(f"  • {l.short():<28} {l.location or '':<30} {l.title[:50]}  {l.url}")
    if not listings:
        console.print("[yellow]0 anúncios. Abra o HTML guardado: se tiver resultados, o parser precisa de ajuste; se não, o URL está errado ou o site bloqueou.[/yellow]")
    return 0


def cmd_parse_file(args) -> int:
    """Corre só o parser sobre um HTML guardado (útil para afinar seletores sem bater no site)."""
    cfg = _config(args)
    search = next((s for s in cfg.searches if s.name == args.search), None) if args.search else cfg.searches[0]
    source = get_source(args.source_name)
    html = Path(args.file).read_text(encoding="utf-8")
    listings = source.parse(html, search, args.url or source.start_url(search))
    console.print(json.dumps([l.to_dict() for l in listings], ensure_ascii=False, indent=2))
    console.print(f"[dim]{len(listings)} anúncios[/dim]")
    return 0


def cmd_telegram_test(args) -> int:
    cfg = _config(args)
    notifier = TelegramNotifier(cfg.telegram)
    if not notifier.ready:
        console.print("[red]TELEGRAM_BOT_TOKEN e/ou TELEGRAM_CHAT_ID em falta (veja .env.example).[/red]")
        return 1
    notifier.send_text("✅ casaradar ligado. Vais receber aqui os novos anúncios.")
    console.print("Mensagem enviada.")
    return 0


def cmd_telegram_chat_id(args) -> int:
    cfg = _config(args)
    if not cfg.telegram.token:
        console.print("[red]TELEGRAM_BOT_TOKEN em falta.[/red]")
        return 1
    notifier = TelegramNotifier(cfg.telegram)
    chats = notifier.get_updates_chat_ids()
    if not chats:
        console.print("Nenhuma conversa encontrada. Abra o bot no Telegram, envie 'olá' e volte a correr este comando.")
        return 1
    for chat_id, name in chats:
        console.print(f"chat_id={chat_id}  ({name})")
    return 0


def cmd_sources(args) -> int:
    for name in SOURCES:
        console.print(f"• {name}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="casaradar", description="Radar pessoal de imóveis em Portugal.")
    p.add_argument("-c", "--config", default="config.yaml", help="caminho do config.yaml (default: ./config.yaml)")
    p.add_argument("-v", "--verbose", action="store_true")
    p.add_argument("--version", action="version", version=f"casaradar {__version__}")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init", help="cria config.yaml e .env a partir dos exemplos")
    s.add_argument("--force", action="store_true")
    s.set_defaults(fn=cmd_init)

    s = sub.add_parser("run", help="corre as pesquisas (uma vez ou em ciclo) e notifica")
    s.add_argument("--once", action="store_true", help="correr uma vez e sair (default se --every não for dado)")
    s.add_argument("--every", type=_parse_interval, help="repetir a cada intervalo, ex. 30m, 2h")
    s.add_argument("--search", help="só esta pesquisa (pelo name)")
    s.add_argument("--source", help="só esta fonte")
    s.add_argument("--no-notify", action="store_true", help="guardar mas não enviar Telegram")
    s.add_argument("--dry-run", action="store_true", help="não guardar nem notificar")
    s.add_argument("--notify-first-run", action="store_true", help="notificar mesmo na primeira execução (por defeito a 1ª só cria a base)")
    s.set_defaults(fn=cmd_run)

    s = sub.add_parser("list", help="mostra os últimos anúncios guardados")
    s.add_argument("--search")
    s.add_argument("--limit", type=int, default=40)
    s.set_defaults(fn=cmd_list)

    s = sub.add_parser("debug-fetch", help="obtém uma página de uma fonte, grava o HTML e mostra o parse")
    s.add_argument("source_name", choices=list(SOURCES))
    s.add_argument("--search", help="pesquisa do config a usar (default: a primeira)")
    s.add_argument("--url", help="usar este URL em vez do construído")
    s.add_argument("--out", default="dumps")
    s.add_argument("--show", type=int, default=10)
    s.set_defaults(fn=cmd_debug_fetch)

    s = sub.add_parser("parse-file", help="corre o parser de uma fonte sobre um HTML guardado")
    s.add_argument("source_name", choices=list(SOURCES))
    s.add_argument("file")
    s.add_argument("--search")
    s.add_argument("--url")
    s.set_defaults(fn=cmd_parse_file)

    s = sub.add_parser("telegram-test", help="envia uma mensagem de teste")
    s.set_defaults(fn=cmd_telegram_test)
    s = sub.add_parser("telegram-chat-id", help="descobre o chat_id das conversas com o bot")
    s.set_defaults(fn=cmd_telegram_chat_id)
    s = sub.add_parser("sources", help="lista as fontes disponíveis")
    s.set_defaults(fn=cmd_sources)
    return p


def main(argv: list[str] | None = None) -> int:
    _load_env()
    args = build_parser().parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO, format="%(message)s", handlers=[RichHandler(console=console, show_path=False, show_time=False)])
    if not args.verbose:
        logging.getLogger("httpx").setLevel(logging.WARNING)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
