from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from .config import ConfigError, load_settings
from .pipeline import PipelineError, reports_dir, run_analysis

log = logging.getLogger("signaldesk")


def setup_logging(verbose: bool = False) -> None:
    logging.basicConfig(
        level=logging.DEBUG if verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not verbose:
        logging.getLogger("signaldesk.scraper").setLevel(logging.ERROR)
        logging.getLogger("trafilatura").setLevel(logging.ERROR)


def cmd_run(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    if args.hours:
        settings.lookback_hours = args.hours
    if args.max_articles:
        settings.max_articles = args.max_articles
    if args.telegram:
        settings.telegram_channels += args.telegram
    report = asyncio.run(run_analysis(settings, args.market))
    if not args.quiet:
        print((reports_dir() / f"{report['id']}.md").read_text(encoding="utf-8"))


def cmd_serve(args: argparse.Namespace) -> None:
    import uvicorn

    from .web import create_app

    uvicorn.run(create_app(), host=args.host, port=args.port, log_level="warning")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="signaldesk",
        description="SignalDesk — AI-аналитик глобального и российского рынков: "
        "что покупать, держать, продавать",
    )
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command")

    run = sub.add_parser("run", help="разовый анализ с выводом отчёта в консоль")
    run.add_argument("-c", "--config", help="путь к config.yaml")
    run.add_argument("-m", "--market", choices=["all", "global", "russia"], default="all")
    run.add_argument("--hours", type=int, help="глубина новостей в часах")
    run.add_argument("-n", "--max-articles", type=int, help="сколько статей читать полностью")
    run.add_argument("-t", "--telegram", nargs="*", default=[], help="телеграм-каналы")
    run.add_argument("-q", "--quiet", action="store_true", help="не печатать отчёт")
    run.set_defaults(func=cmd_run)

    serve = sub.add_parser("serve", help="веб-дашборд")
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8000)
    serve.set_defaults(func=cmd_serve)

    args = parser.parse_args(argv)
    setup_logging(args.verbose)
    if not args.command:
        parser.print_help()
        return
    try:
        args.func(args)
    except (ConfigError, PipelineError) as exc:
        sys.exit(f"Ошибка: {exc}")


if __name__ == "__main__":
    main()
