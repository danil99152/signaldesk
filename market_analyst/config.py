from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .sources import DEFAULT_FEEDS, Feed

DEFAULT_REASONING_MODEL = "deepseek/deepseek-r1"
DEFAULT_FAST_MODEL = "google/gemini-2.5-flash-lite"


@dataclass
class Settings:
    api_key: str
    reasoning_model: str = DEFAULT_REASONING_MODEL
    fast_model: str = DEFAULT_FAST_MODEL
    lookback_hours: int = 24
    max_articles: int = 25
    feeds: list[Feed] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    telegram_channels: list[str] = field(default_factory=list)
    watchlist_global: list[str] = field(default_factory=list)
    watchlist_russia: list[str] = field(default_factory=list)


def load_settings(config_path: str | Path | None = None) -> Settings:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if not api_key:
        raise SystemExit("Не задан OPENROUTER_API_KEY (см. .env.example)")

    data: dict = {}
    path = Path(config_path) if config_path else Path("config.yaml")
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    elif config_path:
        raise SystemExit(f"Файл конфигурации не найден: {path}")

    disabled = set(data.get("disabled_feeds") or [])
    feeds = [f for f in DEFAULT_FEEDS if f.name not in disabled]
    for extra in data.get("extra_feeds") or []:
        feeds.append(Feed(extra["name"], extra["url"], extra.get("region", "global")))

    watchlist = data.get("watchlist") or {}
    return Settings(
        api_key=api_key,
        reasoning_model=os.getenv("REASONING_MODEL", DEFAULT_REASONING_MODEL),
        fast_model=os.getenv("FAST_MODEL", DEFAULT_FAST_MODEL),
        lookback_hours=int(data.get("lookback_hours", 24)),
        max_articles=int(data.get("max_articles", 25)),
        feeds=feeds,
        telegram_channels=list(data.get("telegram_channels") or []),
        watchlist_global=list(watchlist.get("global") or []),
        watchlist_russia=list(watchlist.get("russia") or []),
    )
