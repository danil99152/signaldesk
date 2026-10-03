"""Котировки: Yahoo Finance (глобальный рынок) и ISS Мосбиржи (российский рынок)."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, timedelta

import httpx

log = logging.getLogger(__name__)

YAHOO_URL = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
MOEX_HISTORY_URL = (
    "https://iss.moex.com/iss/history/engines/stock/markets/{market}"
    "/boards/{board}/securities/{ticker}.json"
)
MOEX_INDEXES = {"IMOEX", "RTSI", "MOEXBC", "MOEXOG", "MOEXFN", "MOEXMM", "RGBI", "MOEXIT"}


@dataclass
class Quote:
    ticker: str
    market: str  # "global" | "russia"
    last: float
    change_1d: float | None
    change_1w: float | None
    change_1m: float | None
    currency: str = ""
    history: list[float] = field(default_factory=list)  # дневные закрытия за ~месяц

    def line(self) -> str:
        def pct(v: float | None) -> str:
            return "n/a" if v is None else f"{v:+.1f}%"

        return (
            f"{self.ticker} ({self.market}): {self.last:,.2f} {self.currency} | "
            f"1д {pct(self.change_1d)}, 1н {pct(self.change_1w)}, 1м {pct(self.change_1m)}"
        )


def _changes(closes: list[float]) -> tuple[float | None, float | None, float | None]:
    def ch(n: int) -> float | None:
        if len(closes) <= n or not closes[-1 - n]:
            return None
        return (closes[-1] / closes[-1 - n] - 1) * 100

    return ch(1), ch(5), ch(min(21, max(len(closes) - 1, 1)))


async def yahoo_quote(client: httpx.AsyncClient, ticker: str) -> Quote | None:
    try:
        resp = await client.get(
            YAHOO_URL.format(ticker=ticker), params={"range": "1mo", "interval": "1d"}
        )
        resp.raise_for_status()
        result = resp.json()["chart"]["result"][0]
        closes = [c for c in result["indicators"]["quote"][0]["close"] if c is not None]
        if not closes:
            return None
        d1, w1, m1 = _changes(closes)
        return Quote(
            ticker, "global", closes[-1], d1, w1, m1,
            result["meta"].get("currency", ""), closes[-22:],
        )
    except Exception as exc:
        log.warning("Yahoo %s: %s", ticker, exc)
        return None


async def moex_quote(client: httpx.AsyncClient, ticker: str) -> Quote | None:
    ticker = ticker.upper()
    market, board = ("index", "SNDX") if ticker in MOEX_INDEXES else ("shares", "TQBR")
    params = {
        "iss.meta": "off",
        "from": (date.today() - timedelta(days=40)).isoformat(),
        "history.columns": "TRADEDATE,CLOSE",
    }
    try:
        resp = await client.get(
            MOEX_HISTORY_URL.format(market=market, board=board, ticker=ticker), params=params
        )
        resp.raise_for_status()
        closes = [row[1] for row in resp.json()["history"]["data"] if row[1]]
        if not closes:
            return None
        d1, w1, m1 = _changes(closes)
        return Quote(
            ticker, "russia", closes[-1], d1, w1, m1,
            "pts" if market == "index" else "RUB", closes[-22:],
        )
    except Exception as exc:
        log.warning("MOEX %s: %s", ticker, exc)
        return None


async def get_quotes(
    client: httpx.AsyncClient, global_tickers: list[str], russia_tickers: list[str]
) -> list[Quote]:
    tasks = [yahoo_quote(client, t) for t in dict.fromkeys(global_tickers)]
    tasks += [moex_quote(client, t) for t in dict.fromkeys(russia_tickers)]
    return [q for q in await asyncio.gather(*tasks) if q]
