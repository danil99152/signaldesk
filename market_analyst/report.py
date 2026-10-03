from __future__ import annotations

from datetime import datetime
from pathlib import Path

from .market_data import Quote
from .models import ArticleDigest

ACTION_ICONS = {"BUY": "🟢 ПОКУПАТЬ", "HOLD": "🟡 ДЕРЖАТЬ", "SELL": "🔴 ПРОДАВАТЬ"}
SENTIMENT = {"bullish": "📈 позитивный", "neutral": "➖ нейтральный", "bearish": "📉 негативный"}
HORIZON = {"short": "краткосрочно", "medium": "среднесрочно", "long": "долгосрочно"}

DISCLAIMER = (
    "_Отчёт сгенерирован автоматически языковыми моделями на основе открытых новостей и "
    "не является индивидуальной инвестиционной рекомендацией. Проверяйте данные и "
    "принимайте решения самостоятельно._"
)


def _cell(value) -> str:
    return str(value or "").replace("|", "/").replace("\n", " ")


def _region_section(title: str, data: dict) -> list[str]:
    if not data:
        return []
    lines = [f"## {title}", ""]
    sentiment = SENTIMENT.get(str(data.get("sentiment", "")).lower(), data.get("sentiment", ""))
    if sentiment:
        lines.append(f"**Настроение:** {sentiment}\n")
    if data.get("summary"):
        lines.append(f"{data['summary']}\n")
    for driver in data.get("key_drivers") or []:
        lines.append(f"- {driver}")
    lines.append("")
    return lines


def _recommendations(recs: list[dict], digests: list[ArticleDigest], market: str) -> list[str]:
    recs = [r for r in recs if r.get("market", "global") == market]
    if not recs:
        return []
    order = {"BUY": 0, "HOLD": 1, "SELL": 2}
    recs.sort(key=lambda r: (order.get(str(r.get("action")).upper(), 3), -int(r.get("confidence") or 0)))
    title = "Глобальный рынок" if market == "global" else "Российский рынок"
    lines = [
        f"### {title}",
        "",
        "| Действие | Актив | Горизонт | Уверенность | Обоснование | Риски | Источники |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in recs:
        action = str(r.get("action", "")).upper()
        sources = []
        for sid in r.get("sources") or []:
            try:
                d = digests[int(sid)]
                sources.append(f"[{sid}]({d.item.url})")
            except (ValueError, TypeError, IndexError):
                continue
        conf = int(r.get("confidence") or 0)
        lines.append(
            "| {a} | **{asset}** `{ticker}` | {h} | {c} | {why} | {risk} | {src} |".format(
                a=ACTION_ICONS.get(action, action),
                asset=_cell(r.get("asset")),
                ticker=_cell(r.get("ticker")),
                h=HORIZON.get(r.get("horizon"), _cell(r.get("horizon"))),
                c="★" * conf + "☆" * (5 - conf) if 0 <= conf <= 5 else conf,
                why=_cell(r.get("rationale")),
                risk=_cell(r.get("risks")),
                src=", ".join(sources),
            )
        )
    lines.append("")
    return lines


def render_markdown(
    analysis: dict,
    digests: list[ArticleDigest],
    quotes: list[Quote],
    meta: dict,
) -> str:
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines = [f"# Рыночная аналитика — {now}", ""]

    if "raw" in analysis:
        lines += [analysis["raw"], ""]
    else:
        if analysis.get("market_overview"):
            lines += ["## Общая картина", "", analysis["market_overview"], ""]
        lines += _region_section("Глобальный рынок", analysis.get("global") or {})
        lines += _region_section("Российский рынок", analysis.get("russia") or {})

        recs = [r for r in analysis.get("recommendations") or [] if isinstance(r, dict)]
        if recs:
            lines += ["## Рекомендации", ""]
            lines += _recommendations(recs, digests, "global")
            lines += _recommendations(recs, digests, "russia")

        if analysis.get("key_risks"):
            lines += ["## Ключевые риски", ""] + [f"- {r}" for r in analysis["key_risks"]] + [""]
        if analysis.get("upcoming_events"):
            lines += ["## За чем следить", ""] + [f"- {e}" for e in analysis["upcoming_events"]] + [""]

    if quotes:
        lines += ["## Котировки", "", "```"] + [q.line() for q in quotes] + ["```", ""]

    lines += ["## Использованные новости", ""]
    for i, d in enumerate(digests):
        lines.append(f"{i}. [{d.item.title}]({d.item.url}) — _{d.item.source}_")
    lines += [
        "",
        "---",
        f"Модели: отбор/выжимки — `{meta.get('fast_model')}`, анализ — `{meta.get('reasoning_model')}`. "
        f"Просмотрено заголовков: {meta.get('headlines', 0)}, прочитано статей: {len(digests)}. "
        f"Токены: {meta.get('usage', {})}.",
        "",
        DISCLAIMER,
        "",
    ]
    return "\n".join(lines)


def save_report(markdown: str, analysis: dict, out_dir: str | Path = "reports") -> Path:
    import json

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M")
    md_path = out / f"report_{stamp}.md"
    md_path.write_text(markdown, encoding="utf-8")
    (out / f"report_{stamp}.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return md_path
