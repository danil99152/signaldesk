from datetime import datetime, timedelta, timezone

from market_analyst.analyst import mentioned_tickers, pick_balanced
from market_analyst.llm import extract_json
from market_analyst.market_data import _changes
from market_analyst.models import ArticleDigest, NewsItem
from market_analyst.report import render_markdown
from market_analyst.scraper import (
    _channel_name,
    dedupe,
    filter_recent,
    parse_feed,
    parse_telegram_page,
)
from market_analyst.sources import Feed

RSS = b"""<?xml version="1.0"?><rss version="2.0"><channel><title>t</title>
<item><title>Fed holds rates</title><link>https://ex.com/a</link>
<description>&lt;p&gt;The Fed kept rates&lt;/p&gt;</description>
<pubDate>Sat, 03 Oct 2026 10:00:00 GMT</pubDate></item>
<item><title></title><link>https://ex.com/b</link></item>
</channel></rss>"""

TG_HTML = """<div class="tgme_widget_message" data-post="chan/42">
<div class="tgme_widget_message_text">Сбербанк отчитался\nПрибыль выросла на 10%</div>
<time datetime="2026-10-03T10:00:00+00:00"></time></div>"""


def item(title, region="global", url=None, published=None):
    return NewsItem(title=title, url=url or f"https://ex.com/{title}", source="s",
                    region=region, published=published)


def test_parse_feed():
    items = parse_feed(RSS, Feed("Ex", "u", "global"))
    assert len(items) == 1
    assert items[0].title == "Fed holds rates"
    assert items[0].summary == "The Fed kept rates"
    assert items[0].published == datetime(2026, 10, 3, 10, tzinfo=timezone.utc)


def test_parse_telegram():
    items = parse_telegram_page(TG_HTML, "chan")
    assert items[0].url == "https://t.me/chan/42"
    assert items[0].region == "russia"
    assert items[0].title == "Сбербанк отчитался"
    assert "Прибыль" in items[0].text


def test_channel_name():
    for raw in ("markettwits", "@markettwits", "https://t.me/markettwits", "t.me/s/markettwits/"):
        assert _channel_name(raw) == "markettwits"


def test_dedupe_and_recent():
    now = datetime.now(timezone.utc)
    items = [
        item("Oil up", url="https://ex.com/1?utm=x", published=now),
        item("Oil up!", url="https://ex.com/2", published=now),
        item("Other", url="https://ex.com/1", published=now),
        item("Old", published=now - timedelta(days=3)),
        item("No date"),
    ]
    assert [i.title for i in dedupe(items)] == ["Oil up", "Old", "No date"]
    assert [i.title for i in filter_recent(items, 24)] == ["Oil up", "Oil up!", "Other", "No date"]


def test_extract_json():
    assert extract_json('{"a": 1}') == {"a": 1}
    assert extract_json('<think>hmm {"x":0}</think>```json\n{"a": 2}\n```') == {"a": 2}
    assert extract_json('Вот ответ: {"a": [1, 2]} спасибо') == {"a": [1, 2]}


def test_pick_balanced():
    items = [item(f"g{i}") for i in range(5)] + [item(f"r{i}", "russia") for i in range(5)]
    scores = {0: 10, 1: 9, 2: 8, 3: 7, 4: 6, 5: 2, 6: 1}
    picked = pick_balanced(items, scores, 4)
    assert [i.title for i in picked] == ["g0", "g1", "r0", "r1"]


def test_changes():
    d1, w1, m1 = _changes([100, 100, 100, 100, 100, 110, 121])
    assert round(d1, 1) == 10.0 and round(w1, 1) == 21.0 and round(m1, 1) == 21.0


def test_mentioned_tickers_and_report():
    digests = [
        ArticleDigest(item("A"), "s", assets=[{"ticker": "sber", "market": "russia"},
                                             {"ticker": "NVDA", "market": "global"}]),
        ArticleDigest(item("B"), "s", assets=[{"ticker": "NVDA", "market": "global"}]),
    ]
    assert mentioned_tickers(digests) == (["NVDA"], ["SBER"])

    analysis = {
        "market_overview": "Обзор",
        "global": {"sentiment": "bullish", "summary": "s", "key_drivers": ["ФРС"]},
        "recommendations": [
            {"asset": "Сбер", "ticker": "SBER", "market": "russia", "action": "BUY",
             "horizon": "medium", "confidence": 4, "rationale": "дешёв", "risks": "ставка",
             "sources": [0, 99]},
        ],
    }
    md = render_markdown(analysis, digests, [], {"fast_model": "f", "reasoning_model": "r"})
    assert "🟢 ПОКУПАТЬ" in md and "★★★★☆" in md and "[0](https://ex.com/A)" in md
