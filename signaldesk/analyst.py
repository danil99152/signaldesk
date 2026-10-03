from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone

from .llm import OpenRouter, extract_json
from .market_data import Quote
from .models import ArticleDigest, NewsItem

log = logging.getLogger(__name__)

SELECT_SYSTEM = """Ты — редактор финансовой ленты. Из списка заголовков отбери новости,
которые реально важны для инвестиционных решений на глобальном и российском рынках:
макроэкономика, ставки ЦБ/ФРС, инфляция, сырьё (нефть, газ, металлы, золото), валюты,
отчётности и прогнозы компаний, дивиденды, M&A, IPO, санкции и геополитика с влиянием на рынки,
регуляторные решения, крупные движения индексов и криптовалют.
Игнорируй светскую хронику, спорт, происшествия, рекламу и дубликаты одной и той же истории.
Ответь строго JSON: {"selected": [{"id": <int>, "score": <1-10>}]}"""

DIGEST_SYSTEM = """Ты — финансовый аналитик. Сделай сжатую выжимку новости для инвестора.
Ответь строго JSON:
{
  "summary": "2-4 предложения по-русски: факты, цифры, что произошло",
  "importance": <1-10, насколько это двигает рынки>,
  "macro": "влияние на макро/сектор одной фразой или пустая строка",
  "assets": [
    {"name": "компания/актив", "ticker": "тикер (Yahoo для глобальных, Мосбиржа для РФ) или пусто",
     "market": "global|russia", "sentiment": <-2..2>, "note": "почему"}
  ]
}"""

ANALYST_SYSTEM = """Ты — старший инвестиционный стратег и трейдер с опытом работы на рынках США,
Европы, Азии, сырья, криптовалют и Московской биржи. На основе свежих новостей и котировок
подготовь аналитический обзор и конкретные рекомендации: что ПОКУПАТЬ, что ДЕРЖАТЬ, что ПРОДАВАТЬ.

Правила:
- Опирайся только на предоставленные новости и котировки, ссылайся на них по id (например [12]).
- Разделяй глобальный и российский рынки; учитывай санкции, ключевую ставку ЦБ РФ, курс рубля,
  нефть, ставку ФРС, доходности UST, доллар (DXY), риск-аппетит.
- Для каждой рекомендации укажи горизонт (short: дни–недели, medium: 1–6 мес, long: 6+ мес),
  уверенность 1–5, обоснование и главные риски. Не выдумывай цифры, которых нет во входных данных.
- Обязательно дай рекомендацию по каждому тикеру из списка наблюдения пользователя.
- Предпочитай ликвидные инструменты (акции, индексы/ETF, сырьё, валюты, ОФЗ, крупная крипта).
- Если данных недостаточно — честно ставь HOLD с низкой уверенностью.

Ответ — строго один JSON-объект (без markdown), по-русски:
{
  "market_overview": "общая картина в 3-6 предложениях",
  "global": {"sentiment": "bullish|neutral|bearish", "summary": "...", "key_drivers": ["..."]},
  "russia": {"sentiment": "bullish|neutral|bearish", "summary": "...", "key_drivers": ["..."]},
  "recommendations": [
    {"asset": "название", "ticker": "тикер", "market": "global|russia",
     "action": "BUY|HOLD|SELL", "horizon": "short|medium|long", "confidence": <1-5>,
     "rationale": "...", "risks": "...", "sources": [<id>, ...]}
  ],
  "key_risks": ["..."],
  "upcoming_events": ["события/даты, за которыми следить"]
}"""


def _headline_line(i: int, item: NewsItem) -> str:
    date = item.published.strftime("%m-%d %H:%M") if item.published else "--"
    return f"{i}. [{item.region}|{item.source}|{date}] {item.title}"


async def select_links(
    llm: OpenRouter,
    model: str,
    items: list[NewsItem],
    max_articles: int,
    batch_size: int = 150,
) -> list[NewsItem]:
    """Быстрая модель оценивает заголовки и отбирает самые важные ссылки."""
    scores: dict[int, int] = {}

    async def score_batch(start: int) -> None:
        batch = items[start : start + batch_size]
        listing = "\n".join(_headline_line(start + i, it) for i, it in enumerate(batch))
        try:
            data = await llm.chat_json(
                model,
                [
                    {"role": "system", "content": SELECT_SYSTEM},
                    {"role": "user", "content": f"Заголовки:\n{listing}"},
                ],
                temperature=0,
            )
        except Exception as exc:
            log.warning("Отбор пачки %d не удался: %s", start, exc)
            return
        for entry in data.get("selected", []) if isinstance(data, dict) else []:
            try:
                idx, score = int(entry["id"]), int(entry.get("score", 5))
            except (KeyError, TypeError, ValueError):
                continue
            if 0 <= idx < len(items):
                scores[idx] = max(scores.get(idx, 0), score)

    await asyncio.gather(*(score_batch(s) for s in range(0, len(items), batch_size)))
    return pick_balanced(items, scores, max_articles)


def pick_balanced(
    items: list[NewsItem], scores: dict[int, int], max_articles: int
) -> list[NewsItem]:
    """Берёт лучшие новости, гарантируя каждому региону примерно половину квоты."""
    ranked = sorted(scores, key=lambda i: scores[i], reverse=True)
    quota = max_articles // 2
    chosen: list[int] = []
    for region in ("global", "russia"):
        chosen += [i for i in ranked if items[i].region == region][:quota]
    for i in ranked:
        if len(chosen) >= max_articles:
            break
        if i not in chosen:
            chosen.append(i)
    chosen.sort(key=lambda i: scores[i], reverse=True)
    return [items[i] for i in chosen[:max_articles]]


async def digest_articles(
    llm: OpenRouter, model: str, items: list[NewsItem], concurrency: int = 6
) -> list[ArticleDigest]:
    sem = asyncio.Semaphore(concurrency)

    async def digest(item: NewsItem) -> ArticleDigest | None:
        body = item.text or item.summary or item.title
        async with sem:
            try:
                data = await llm.chat_json(
                    model,
                    [
                        {"role": "system", "content": DIGEST_SYSTEM},
                        {
                            "role": "user",
                            "content": f"Источник: {item.source}\nЗаголовок: {item.title}\n\n{body}",
                        },
                    ],
                    temperature=0,
                )
            except Exception as exc:
                log.warning("Выжимка не удалась (%s): %s", item.url, exc)
                return ArticleDigest(item=item, summary=item.summary or item.title)
        if not isinstance(data, dict):
            return ArticleDigest(item=item, summary=item.summary or item.title)
        return ArticleDigest(
            item=item,
            summary=str(data.get("summary", "")),
            assets=[a for a in data.get("assets") or [] if isinstance(a, dict)],
            macro=str(data.get("macro", "")),
            importance=int(data.get("importance") or 0),
        )

    results = await asyncio.gather(*(digest(i) for i in items))
    return [r for r in results if r]


def mentioned_tickers(digests: list[ArticleDigest], limit: int = 15) -> tuple[list[str], list[str]]:
    """Тикеры, упомянутые в новостях (по частоте), — для подтягивания котировок."""
    counts: dict[tuple[str, str], int] = {}
    for d in digests:
        for a in d.assets:
            ticker = str(a.get("ticker") or "").strip().upper()
            market = a.get("market", "global")
            if ticker and " " not in ticker and len(ticker) <= 12:
                key = (market, ticker)
                counts[key] = counts.get(key, 0) + 1
    top = sorted(counts, key=counts.get, reverse=True)[:limit]
    return [t for m, t in top if m != "russia"], [t for m, t in top if m == "russia"]


def build_analyst_prompt(
    digests: list[ArticleDigest],
    quotes: list[Quote],
    watchlist_global: list[str],
    watchlist_russia: list[str],
) -> str:
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    news = []
    for i, d in enumerate(digests):
        assets = "; ".join(
            f"{a.get('name')} ({a.get('ticker') or '-'}, {a.get('market')}, sent {a.get('sentiment')}): {a.get('note', '')}"
            for a in d.assets
        )
        news.append(
            f"[{i}] ({d.item.region}, {d.item.source}, важность {d.importance}) {d.item.title}\n"
            f"    {d.summary}\n"
            + (f"    Макро: {d.macro}\n" if d.macro else "")
            + (f"    Активы: {assets}\n" if assets else "")
        )
    quote_lines = "\n".join(q.line() for q in quotes) or "нет данных"
    return (
        f"Текущее время: {now}\n\n"
        f"Список наблюдения пользователя:\n"
        f"  глобальный рынок: {', '.join(watchlist_global) or '-'}\n"
        f"  российский рынок: {', '.join(watchlist_russia) or '-'}\n\n"
        f"Котировки:\n{quote_lines}\n\n"
        f"Новости:\n" + "\n".join(news)
    )


async def analyze(llm: OpenRouter, model: str, prompt: str) -> dict:
    text = await llm.chat(
        model,
        [
            {"role": "system", "content": ANALYST_SYSTEM},
            {"role": "user", "content": prompt},
        ],
        temperature=0.3,
    )
    try:
        data = extract_json(text)
        if isinstance(data, dict):
            return data
    except (ValueError, json.JSONDecodeError):
        pass
    log.warning("Модель вернула не-JSON ответ, сохраняю как текст")
    return {"raw": text}
