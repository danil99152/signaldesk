from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Feed:
    name: str
    url: str
    region: str  # "global" | "russia"


DEFAULT_FEEDS: list[Feed] = [
    # --- Глобальный рынок ---
    Feed("CNBC Markets", "https://www.cnbc.com/id/100003114/device/rss/rss.html", "global"),
    Feed("CNBC Finance", "https://www.cnbc.com/id/10000664/device/rss/rss.html", "global"),
    Feed("MarketWatch Top Stories", "https://feeds.content.dowjones.io/public/rss/mw_topstories", "global"),
    Feed("MarketWatch Market Pulse", "https://feeds.content.dowjones.io/public/rss/mw_marketpulse", "global"),
    Feed("WSJ Markets", "https://feeds.content.dowjones.io/public/rss/RSSMarketsMain", "global"),
    Feed("Bloomberg Markets", "https://feeds.bloomberg.com/markets/news.rss", "global"),
    Feed("FT Markets", "https://www.ft.com/markets?format=rss", "global"),
    Feed("Yahoo Finance", "https://finance.yahoo.com/news/rssindex", "global"),
    Feed("Investing.com Stocks", "https://www.investing.com/rss/news_25.rss", "global"),
    Feed("Investing.com Economy", "https://www.investing.com/rss/news_14.rss", "global"),
    Feed("Seeking Alpha Market Currents", "https://seekingalpha.com/market_currents.xml", "global"),
    Feed("Federal Reserve", "https://www.federalreserve.gov/feeds/press_all.xml", "global"),
    Feed("OilPrice", "https://oilprice.com/rss/main", "global"),
    Feed("CoinDesk", "https://www.coindesk.com/arc/outboundfeeds/rss/", "global"),
    # --- Российский рынок ---
    Feed("РБК", "https://rssexport.rbc.ru/rbcnews/news/30/full.rss", "russia"),
    Feed("Интерфакс", "https://www.interfax.ru/rss.asp", "russia"),
    Feed("Коммерсантъ Экономика", "https://www.kommersant.ru/RSS/section-economics.xml", "russia"),
    Feed("Коммерсантъ Финансы", "https://www.kommersant.ru/RSS/section-finance.xml", "russia"),
    Feed("Ведомости", "https://www.vedomosti.ru/rss/news", "russia"),
    Feed("ТАСС", "https://tass.ru/rss/v2.xml", "russia"),
    Feed("ПРАЙМ", "https://1prime.ru/export/rss2/index.xml", "russia"),
    Feed("Smart-Lab", "https://smart-lab.ru/rss/", "russia"),
    Feed("Investing.com RU", "https://ru.investing.com/rss/news_25.rss", "russia"),
    Feed("Frank Media", "https://frankmedia.ru/feed", "russia"),
    Feed("Банк России", "https://www.cbr.ru/rss/eventrss", "russia"),
]
