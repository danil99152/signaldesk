from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class NewsItem:
    title: str
    url: str
    source: str
    region: str  # "global" | "russia"
    summary: str = ""
    published: datetime | None = None
    text: str = ""  # полный текст (заполняется после отбора)
    kind: str = "news"  # "news" | "telegram"


@dataclass
class ArticleDigest:
    item: NewsItem
    summary: str
    assets: list[dict] = field(default_factory=list)
    macro: str = ""
    importance: int = 0
