from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from . import analyst, market_data, scraper
from .config import load_settings
from .llm import OpenRouter
from .report import render_markdown, save_report

log = logging.getLogger("market_analyst")


async def run(args: argparse.Namespace) -> None:
    settings = load_settings(args.config)
    if args.hours:
        settings.lookback_hours = args.hours
    if args.max_articles:
        settings.max_articles = args.max_articles
    if args.telegram:
        settings.telegram_channels += args.telegram
    if args.market != "all":
        settings.feeds = [f for f in settings.feeds if f.region == args.market]
        if args.market == "global":
            settings.watchlist_russia = []
        else:
            settings.watchlist_global = []

    llm = OpenRouter(settings.api_key)
    try:
        async with scraper.make_client() as http:
            log.info("1/5 Сбор новостей: %d лент, %d телеграм-каналов",
                     len(settings.feeds), len(settings.telegram_channels))
            items = await scraper.collect_news(
                http, settings.feeds, settings.telegram_channels, settings.lookback_hours
            )
            if args.market != "all":
                items = [i for i in items if i.region == args.market]
            if not items:
                raise SystemExit("Не удалось собрать ни одной новости")
            log.info("   собрано %d уникальных заголовков", len(items))

            log.info("2/5 Отбор ссылок моделью %s", settings.fast_model)
            selected = await analyst.select_links(
                llm, settings.fast_model, items, settings.max_articles
            )
            if not selected:
                log.warning("Модель ничего не отобрала, беру самые свежие новости")
                selected = items[: settings.max_articles]
            log.info("   отобрано %d статей", len(selected))

            log.info("3/5 Загрузка и выжимка статей")
            await scraper.fetch_articles(http, selected)
            digests = await analyst.digest_articles(llm, settings.fast_model, selected)
            digests.sort(key=lambda d: d.importance, reverse=True)

            log.info("4/5 Котировки")
            news_global, news_russia = analyst.mentioned_tickers(digests)
            quotes = await market_data.get_quotes(
                http,
                settings.watchlist_global + news_global,
                settings.watchlist_russia + news_russia,
            )

        log.info("5/5 Анализ моделью %s (может занять пару минут)", settings.reasoning_model)
        prompt = analyst.build_analyst_prompt(
            digests, quotes, settings.watchlist_global, settings.watchlist_russia
        )
        analysis = await analyst.analyze(llm, settings.reasoning_model, prompt)

        markdown = render_markdown(
            analysis,
            digests,
            quotes,
            {
                "fast_model": settings.fast_model,
                "reasoning_model": settings.reasoning_model,
                "headlines": len(items),
                "usage": llm.usage,
            },
        )
        path = save_report(markdown, analysis, args.out)
        log.info("Отчёт сохранён: %s", path)
        if not args.quiet:
            print(markdown)
    finally:
        await llm.aclose()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        prog="market-analyst",
        description="AI-аналитик глобального и российского рынков: что покупать, держать, продавать",
    )
    parser.add_argument("-c", "--config", help="путь к config.yaml")
    parser.add_argument("-m", "--market", choices=["all", "global", "russia"], default="all")
    parser.add_argument("--hours", type=int, help="глубина новостей в часах")
    parser.add_argument("-n", "--max-articles", type=int, help="сколько статей читать полностью")
    parser.add_argument("-t", "--telegram", nargs="*", default=[], help="телеграм-каналы")
    parser.add_argument("-o", "--out", default="reports", help="папка для отчётов")
    parser.add_argument("-q", "--quiet", action="store_true", help="не печатать отчёт")
    parser.add_argument("-v", "--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%H:%M:%S",
        stream=sys.stderr,
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)
    if not args.verbose:
        logging.getLogger("market_analyst.scraper").setLevel(logging.ERROR)
        logging.getLogger("trafilatura").setLevel(logging.ERROR)
    asyncio.run(run(args))


if __name__ == "__main__":
    main()
