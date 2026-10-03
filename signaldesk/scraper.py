from __future__ import annotations

import asyncio
import logging
import re
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import feedparser
import httpx
import trafilatura
from bs4 import BeautifulSoup

from .models import NewsItem
from .sources import Feed

log = logging.getLogger(__name__)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/129.0 Safari/537.36"
)
HEADERS = {"User-Agent": USER_AGENT, "Accept-Language": "en-US,en;q=0.9,ru;q=0.8"}


def make_client(timeout: float = 20.0) -> httpx.AsyncClient:
    return httpx.AsyncClient(headers=HEADERS, timeout=timeout, follow_redirects=True)


def _clean_html(html: str) -> str:
    return re.sub(r"\s+", " ", BeautifulSoup(html or "", "lxml").get_text(" ")).strip()


def _entry_date(entry) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        value = entry.get(key)
        if value:
            return datetime(*value[:6], tzinfo=timezone.utc)
    for key in ("published", "updated"):
        value = entry.get(key)
        if value:
            try:
                dt = parsedate_to_datetime(value)
                return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)
            except (TypeError, ValueError):
                pass
    return None


def parse_feed(content: bytes, feed: Feed) -> list[NewsItem]:
    parsed = feedparser.parse(content)
    items = []
    for entry in parsed.entries:
        title = _clean_html(entry.get("title", ""))
        link = entry.get("link", "")
        if not title or not link:
            continue
        items.append(
            NewsItem(
                title=title,
                url=link,
                source=feed.name,
                region=feed.region,
                summary=_clean_html(entry.get("summary", ""))[:500],
                published=_entry_date(entry),
            )
        )
    return items


async def fetch_feed(client: httpx.AsyncClient, feed: Feed) -> list[NewsItem]:
    try:
        resp = await client.get(feed.url)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("RSS %s недоступен: %s", feed.name, exc)
        return []
    items = parse_feed(resp.content, feed)
    log.info("RSS %s: %d новостей", feed.name, len(items))
    return items


def _channel_name(channel: str) -> str:
    channel = channel.strip().rstrip("/")
    channel = re.sub(r"^(https?://)?(www\.)?t(elegram)?\.me/(s/)?", "", channel)
    return channel.lstrip("@")


def parse_telegram_page(html: str, channel: str) -> list[NewsItem]:
    soup = BeautifulSoup(html, "lxml")
    items = []
    for msg in soup.select(".tgme_widget_message"):
        text_el = msg.select_one(".tgme_widget_message_text")
        if not text_el:
            continue
        text = text_el.get_text("\n").strip()
        post = msg.get("data-post", "")
        url = f"https://t.me/{post}" if post else f"https://t.me/{channel}"
        published = None
        time_el = msg.select_one("time[datetime]")
        if time_el:
            try:
                published = datetime.fromisoformat(time_el["datetime"])
            except ValueError:
                pass
        first_line = text.split("\n", 1)[0]
        items.append(
            NewsItem(
                title=first_line[:200],
                url=url,
                source=f"t.me/{channel}",
                region="russia" if re.search("[а-яА-Я]", text) else "global",
                summary=text[:500],
                published=published,
                text=text,
                kind="telegram",
            )
        )
    return items


async def fetch_telegram(client: httpx.AsyncClient, channel: str) -> list[NewsItem]:
    """Читает публичный канал через веб-превью t.me/s/<channel> (без API-ключей)."""
    name = _channel_name(channel)
    try:
        resp = await client.get(f"https://t.me/s/{name}")
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.warning("Telegram %s недоступен: %s", name, exc)
        return []
    items = parse_telegram_page(resp.text, name)
    log.info("Telegram %s: %d постов", name, len(items))
    return items


def filter_recent(items: list[NewsItem], hours: int) -> list[NewsItem]:
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    # Новости без даты оставляем: многие ленты отдают только свежие записи.
    return [i for i in items if i.published is None or i.published >= cutoff]


def dedupe(items: list[NewsItem]) -> list[NewsItem]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    result = []
    for item in items:
        url_key = item.url.split("?")[0].rstrip("/")
        title_key = re.sub(r"\W+", "", item.title.lower())[:80]
        if url_key in seen_urls or title_key in seen_titles:
            continue
        seen_urls.add(url_key)
        seen_titles.add(title_key)
        result.append(item)
    return result


async def collect_news(
    client: httpx.AsyncClient,
    feeds: list[Feed],
    telegram_channels: list[str],
    lookback_hours: int,
) -> list[NewsItem]:
    tasks = [fetch_feed(client, f) for f in feeds]
    tasks += [fetch_telegram(client, c) for c in telegram_channels]
    results = await asyncio.gather(*tasks)
    items = [item for batch in results for item in batch]
    items = dedupe(filter_recent(items, lookback_hours))
    items.sort(
        key=lambda i: i.published or datetime.now(timezone.utc), reverse=True
    )
    return items


async def fetch_article_text(
    client: httpx.AsyncClient, item: NewsItem, max_chars: int = 6000
) -> str:
    if item.text:
        return item.text[:max_chars]
    try:
        resp = await client.get(item.url)
        resp.raise_for_status()
        text = trafilatura.extract(resp.text, include_comments=False) or ""
    except Exception as exc:  # сеть, пейволл, кривой HTML
        log.debug("Не удалось загрузить %s: %s", item.url, exc)
        text = ""
    # Если статья закрыта пейволлом, работаем хотя бы с анонсом из RSS.
    return (text or item.summary)[:max_chars]


async def fetch_articles(
    client: httpx.AsyncClient, items: list[NewsItem], concurrency: int = 8
) -> None:
    sem = asyncio.Semaphore(concurrency)

    async def worker(item: NewsItem) -> None:
        async with sem:
            item.text = await fetch_article_text(client, item)

    await asyncio.gather(*(worker(i) for i in items))
