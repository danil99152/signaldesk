"""Полный цикл анализа: новости → отбор → выжимки → котировки → рекомендации → отчёт."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict
from datetime import datetime
from pathlib import Path
from typing import Callable

from . import analyst, market_data, scraper
from .config import Settings, data_dir
from .llm import OpenRouter
from .models import ArticleDigest
from .report import render_markdown

log = logging.getLogger(__name__)

Progress = Callable[[int, str], None]
STAGES = 5


class PipelineError(RuntimeError):
    pass


def reports_dir() -> Path:
    return data_dir() / "reports"


def _digest_dict(d: ArticleDigest) -> dict:
    return {
        "title": d.item.title,
        "url": d.item.url,
        "source": d.item.source,
        "region": d.item.region,
        "kind": d.item.kind,
        "published": d.item.published.isoformat() if d.item.published else None,
        "summary": d.summary,
        "importance": d.importance,
        "macro": d.macro,
        "assets": d.assets,
    }


async def run_analysis(
    settings: Settings,
    market: str = "all",
    progress: Progress | None = None,
) -> dict:
    """Запускает анализ, сохраняет отчёт (.json + .md) и возвращает его как словарь."""

    def step(n: int, text: str) -> None:
        log.info("%d/%d %s", n, STAGES, text)
        if progress:
            progress(n, text)

    if not settings.api_key:
        raise PipelineError("Не задан OPENROUTER_API_KEY — добавьте его в .env и перезапустите")

    feeds = settings.feeds
    watch_global, watch_russia = settings.watchlist_global, settings.watchlist_russia
    if market != "all":
        feeds = [f for f in feeds if f.region == market]
        watch_global = watch_global if market == "global" else []
        watch_russia = watch_russia if market == "russia" else []

    llm = OpenRouter(settings.api_key)
    try:
        async with scraper.make_client() as http:
            step(1, f"Сбор новостей: {len(feeds)} лент, {len(settings.telegram_channels)} Telegram-каналов")
            items = await scraper.collect_news(
                http, feeds, settings.telegram_channels, settings.lookback_hours
            )
            if market != "all":
                items = [i for i in items if i.region == market]
            if not items:
                raise PipelineError("Не удалось собрать ни одной новости")

            step(2, f"Отбор важного из {len(items)} заголовков ({settings.fast_model})")
            selected = await analyst.select_links(
                llm, settings.fast_model, items, settings.max_articles
            )
            if not selected:
                log.warning("Модель ничего не отобрала, беру самые свежие новости")
                selected = items[: settings.max_articles]

            step(3, f"Чтение и выжимка {len(selected)} статей")
            await scraper.fetch_articles(http, selected)
            digests = await analyst.digest_articles(llm, settings.fast_model, selected)
            digests.sort(key=lambda d: d.importance, reverse=True)

            step(4, "Котировки Yahoo Finance и Мосбиржи")
            news_global, news_russia = analyst.mentioned_tickers(digests)
            if market == "global":
                news_russia = []
            elif market == "russia":
                news_global = []
            quotes = await market_data.get_quotes(
                http, watch_global + news_global, watch_russia + news_russia
            )

        step(5, f"Анализ и рекомендации ({settings.reasoning_model}) — пара минут")
        prompt = analyst.build_analyst_prompt(digests, quotes, watch_global, watch_russia)
        analysis = await analyst.analyze(llm, settings.reasoning_model, prompt)
    finally:
        await llm.aclose()

    created = datetime.now()
    report_id = created.strftime("%Y%m%d_%H%M%S")
    meta = {
        "fast_model": settings.fast_model,
        "reasoning_model": settings.reasoning_model,
        "headlines": len(items),
        "usage": llm.usage,
        "lookback_hours": settings.lookback_hours,
    }
    report = {
        "id": report_id,
        "created_at": created.isoformat(timespec="seconds"),
        "market": market,
        "analysis": analysis,
        "news": [_digest_dict(d) for d in digests],
        "quotes": [asdict(q) for q in quotes],
        "watchlist": {"global": watch_global, "russia": watch_russia},
        "meta": meta,
    }

    out = reports_dir()
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{report_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (out / f"{report_id}.md").write_text(
        render_markdown(analysis, digests, quotes, meta), encoding="utf-8"
    )
    log.info("Отчёт сохранён: %s", out / f"{report_id}.md")
    return report


def list_reports() -> list[dict]:
    result = []
    for path in sorted(reports_dir().glob("*.json"), reverse=True):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        recs = (data.get("analysis") or {}).get("recommendations") or []
        counts = {"BUY": 0, "HOLD": 0, "SELL": 0}
        for r in recs:
            action = str(r.get("action", "")).upper() if isinstance(r, dict) else ""
            if action in counts:
                counts[action] += 1
        result.append(
            {
                "id": data.get("id", path.stem),
                "created_at": data.get("created_at"),
                "market": data.get("market", "all"),
                "counts": counts,
            }
        )
    return result


def load_report(report_id: str) -> dict | None:
    if not report_id.replace("_", "").isalnum():
        return None
    path = reports_dir() / f"{report_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))
