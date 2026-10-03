from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv

from .sources import DEFAULT_FEEDS, Feed

DEFAULT_REASONING_MODEL = "deepseek/deepseek-r1"
DEFAULT_FAST_MODEL = "google/gemini-2.5-flash-lite"


class ConfigError(RuntimeError):
    pass


def data_dir() -> Path:
    return Path(os.getenv("SIGNALDESK_DATA", "data"))


def config_path() -> Path:
    return Path(os.getenv("SIGNALDESK_CONFIG", "config.yaml"))


@dataclass
class Settings:
    api_key: str
    reasoning_model: str = DEFAULT_REASONING_MODEL
    fast_model: str = DEFAULT_FAST_MODEL
    lookback_hours: int = 24
    max_articles: int = 25
    feeds: list[Feed] = field(default_factory=lambda: list(DEFAULT_FEEDS))
    disabled_feeds: list[str] = field(default_factory=list)
    telegram_channels: list[str] = field(default_factory=list)
    watchlist_global: list[str] = field(default_factory=list)
    watchlist_russia: list[str] = field(default_factory=list)


def read_config_file(path: str | Path | None = None) -> dict:
    path = Path(path) if path else config_path()
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def write_config_file(data: dict, path: str | Path | None = None) -> None:
    path = Path(path) if path else config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(data, allow_unicode=True, sort_keys=False), encoding="utf-8")


def load_settings(path: str | Path | None = None, require_key: bool = True) -> Settings:
    load_dotenv()
    api_key = os.getenv("OPENROUTER_API_KEY", "")
    if require_key and not api_key:
        raise ConfigError("Не задан OPENROUTER_API_KEY (см. .env.example)")
    if path and not Path(path).exists():
        raise ConfigError(f"Файл конфигурации не найден: {path}")

    data = read_config_file(path)
    disabled = list(data.get("disabled_feeds") or [])
    feeds = [f for f in DEFAULT_FEEDS if f.name not in disabled]
    for extra in data.get("extra_feeds") or []:
        feeds.append(Feed(extra["name"], extra["url"], extra.get("region", "global")))

    watchlist = data.get("watchlist") or {}
    return Settings(
        api_key=api_key,
        reasoning_model=os.getenv("REASONING_MODEL") or DEFAULT_REASONING_MODEL,
        fast_model=os.getenv("FAST_MODEL") or DEFAULT_FAST_MODEL,
        lookback_hours=int(data.get("lookback_hours", 24)),
        max_articles=int(data.get("max_articles", 25)),
        feeds=feeds,
        disabled_feeds=disabled,
        telegram_channels=list(data.get("telegram_channels") or []),
        watchlist_global=list(watchlist.get("global") or []),
        watchlist_russia=list(watchlist.get("russia") or []),
    )
