from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import re

import httpx


_COIN_ALIASES: dict[str, tuple[str, str]] = {
    "btc": ("bitcoin", "BTC"),
    "bitcoin": ("bitcoin", "BTC"),
    "eth": ("ethereum", "ETH"),
    "ethereum": ("ethereum", "ETH"),
    "sol": ("solana", "SOL"),
    "solana": ("solana", "SOL"),
    "xrp": ("ripple", "XRP"),
    "ripple": ("ripple", "XRP"),
    "bnb": ("binancecoin", "BNB"),
    "binance": ("binancecoin", "BNB"),
    "doge": ("dogecoin", "DOGE"),
    "dogecoin": ("dogecoin", "DOGE"),
}

_STOCK_ALIASES: dict[str, str] = {
    "aapl": "AAPL",
    "apple": "AAPL",
    "msft": "MSFT",
    "microsoft": "MSFT",
    "nvda": "NVDA",
    "nvidia": "NVDA",
    "tsla": "TSLA",
    "tesla": "TSLA",
    "amzn": "AMZN",
    "amazon": "AMZN",
    "googl": "GOOGL",
    "google": "GOOGL",
    "meta": "META",
    "bbca": "BBCA.JK",
    "bbri": "BBRI.JK",
    "bmri": "BMRI.JK",
    "tlkm": "TLKM.JK",
    "asii": "ASII.JK",
    "goto": "GOTO.JK",
}

_PRICE_HINTS = (
    "harga",
    "price",
    "berapa",
    "kurs",
    "usd",
    "idr",
    "naik",
    "turun",
    "market cap",
    "kapitalisasi",
)

_STOCK_HINTS = (
    "saham",
    "stock",
    "nasdaq",
    "nyse",
    "ihsg",
    "idx",
    "bbca",
    "tlkm",
    "goto",
)


@dataclass
class CryptoQuote:
    coin_id: str
    symbol: str
    usd: float | None
    idr: float | None
    usd_24h_change: float | None
    idr_24h_change: float | None
    fetched_at: str


@dataclass
class StockQuote:
    symbol: str
    short_name: str | None
    currency: str | None
    price: float | None
    change_pct: float | None
    fetched_at: str


def looks_like_crypto_price_query(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    has_coin = any(k in t for k in _COIN_ALIASES)
    has_hint = any(k in t for k in _PRICE_HINTS)
    return has_coin and has_hint


def looks_like_market_price_query(text: str) -> bool:
    t = (text or "").lower()
    if not t:
        return False
    has_hint = any(k in t for k in _PRICE_HINTS)
    has_crypto = any(k in t for k in _COIN_ALIASES)
    has_stock = any(k in t for k in _STOCK_ALIASES) or mentions_stock_terms(t)
    return has_hint and (has_crypto or has_stock)


def mentions_stock_terms(text: str) -> bool:
    t = (text or "").lower()
    return any(k in t for k in _STOCK_HINTS)


def _extract_coin_ids(text: str) -> list[tuple[str, str]]:
    t = (text or "").lower()
    found: list[tuple[str, str]] = []
    seen: set[str] = set()
    for alias, coin in _COIN_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            if coin[0] not in seen:
                found.append(coin)
                seen.add(coin[0])
    return found[:4]


def _extract_stock_symbols(text: str) -> list[str]:
    t = (text or "").lower()
    found: list[str] = []
    seen: set[str] = set()
    for alias, symbol in _STOCK_ALIASES.items():
        if re.search(rf"\b{re.escape(alias)}\b", t):
            if symbol not in seen:
                found.append(symbol)
                seen.add(symbol)
    return found[:4]


async def fetch_crypto_quotes(query: str, timeout_s: float = 15.0) -> list[CryptoQuote]:
    coins = _extract_coin_ids(query)
    if not coins:
        return []
    ids = ",".join(coin_id for coin_id, _ in coins)
    url = (
        "https://api.coingecko.com/api/v3/simple/price"
        f"?ids={ids}&vs_currencies=usd,idr"
        "&include_24hr_change=true"
    )
    headers = {"User-Agent": "BotNesia/1.0"}
    async with httpx.AsyncClient(timeout=timeout_s, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        payload = r.json() or {}

    fetched_at = datetime.now(timezone.utc).isoformat()
    out: list[CryptoQuote] = []
    for coin_id, symbol in coins:
        item = payload.get(coin_id) or {}
        out.append(
            CryptoQuote(
                coin_id=coin_id,
                symbol=symbol,
                usd=item.get("usd"),
                idr=item.get("idr"),
                usd_24h_change=item.get("usd_24h_change"),
                idr_24h_change=item.get("idr_24h_change"),
                fetched_at=fetched_at,
            )
        )
    return out


async def fetch_stock_quotes(query: str, timeout_s: float = 15.0) -> list[StockQuote]:
    symbols = _extract_stock_symbols(query)
    if not symbols:
        return []
    joined = ",".join(symbols)
    url = f"https://query1.finance.yahoo.com/v7/finance/quote?symbols={joined}"
    headers = {"User-Agent": "BotNesia/1.0"}
    async with httpx.AsyncClient(timeout=timeout_s, headers=headers) as client:
        r = await client.get(url)
        r.raise_for_status()
        payload = r.json() or {}
    results = ((payload.get("quoteResponse") or {}).get("result") or [])
    fetched_at = datetime.now(timezone.utc).isoformat()
    out: list[StockQuote] = []
    by_symbol = {str(item.get("symbol") or "").upper(): item for item in results}
    for symbol in symbols:
        item = by_symbol.get(symbol.upper()) or {}
        out.append(
            StockQuote(
                symbol=symbol,
                short_name=item.get("shortName") or item.get("longName"),
                currency=item.get("currency"),
                price=item.get("regularMarketPrice"),
                change_pct=item.get("regularMarketChangePercent"),
                fetched_at=fetched_at,
            )
        )
    return out


def build_crypto_market_context(quotes: list[CryptoQuote]) -> str:
    if not quotes:
        return ""
    lines = [f"Waktu data pasar (UTC): {quotes[0].fetched_at}", "Harga kripto real-time:"]
    for q in quotes:
        usd = f"${q.usd:,.2f}" if isinstance(q.usd, (int, float)) else "n/a"
        idr = f"Rp{q.idr:,.0f}" if isinstance(q.idr, (int, float)) else "n/a"
        chg = (
            f"{q.usd_24h_change:+.2f}%"
            if isinstance(q.usd_24h_change, (int, float))
            else "n/a"
        )
        lines.append(f"- {q.symbol}: {usd} | {idr} | 24 jam: {chg}")
    return "\n".join(lines).strip()


def build_stock_market_context(quotes: list[StockQuote]) -> str:
    if not quotes:
        return ""
    lines = [f"Waktu data pasar (UTC): {quotes[0].fetched_at}", "Harga saham real-time:"]
    for q in quotes:
        currency = q.currency or "USD"
        price = f"{currency} {q.price:,.2f}" if isinstance(q.price, (int, float)) else "n/a"
        chg = f"{q.change_pct:+.2f}%" if isinstance(q.change_pct, (int, float)) else "n/a"
        label = q.short_name or q.symbol
        lines.append(f"- {label} ({q.symbol}): {price} | perubahan: {chg}")
    return "\n".join(lines).strip()


def _format_market_timestamp(raw: str) -> str:
    text = (raw or "").strip()
    if not text:
        return ""
    if "T" in text and ("+00:00" in text or text.endswith("Z")):
        return text.replace("T", " ").replace("+00:00", " UTC").replace("Z", " UTC")
    return text


def format_crypto_market_answer(quotes: list[CryptoQuote]) -> str:
    if not quotes:
        return ""
    parts: list[str] = []
    for q in quotes:
        usd = f"${q.usd:,.2f}" if isinstance(q.usd, (int, float)) else "n/a"
        idr = f"Rp{q.idr:,.0f}" if isinstance(q.idr, (int, float)) else "n/a"
        chg = (
            f"{q.usd_24h_change:+.2f}%"
            if isinstance(q.usd_24h_change, (int, float))
            else "n/a"
        )
        parts.append(f"Harga {q.symbol} saat ini sekitar {usd} atau {idr}, perubahan 24 jam {chg}.")
    stamp = _format_market_timestamp(quotes[0].fetched_at)
    return " ".join(parts) + f" Data diambil pada {stamp}."


def format_stock_market_answer(quotes: list[StockQuote]) -> str:
    if not quotes:
        return ""
    parts: list[str] = []
    for q in quotes:
        currency = q.currency or "USD"
        price = f"{currency} {q.price:,.2f}" if isinstance(q.price, (int, float)) else "n/a"
        chg = f"{q.change_pct:+.2f}%" if isinstance(q.change_pct, (int, float)) else "n/a"
        label = q.short_name or q.symbol
        parts.append(f"Harga {label} ({q.symbol}) saat ini sekitar {price}, perubahan {chg}.")
    stamp = _format_market_timestamp(quotes[0].fetched_at)
    return " ".join(parts) + f" Data diambil pada {stamp}."


def combine_market_answers(
    crypto_quotes: list[CryptoQuote],
    stock_quotes: list[StockQuote],
) -> str:
    parts: list[str] = []
    timestamps: list[str] = []

    for q in stock_quotes:
        currency = q.currency or "USD"
        price = f"{currency} {q.price:,.2f}" if isinstance(q.price, (int, float)) else "n/a"
        chg = f"{q.change_pct:+.2f}%" if isinstance(q.change_pct, (int, float)) else "n/a"
        label = q.short_name or q.symbol
        parts.append(f"Harga {label} ({q.symbol}) saat ini sekitar {price}, perubahan {chg}.")
        if q.fetched_at:
            timestamps.append(q.fetched_at)

    for q in crypto_quotes:
        usd = f"${q.usd:,.2f}" if isinstance(q.usd, (int, float)) else "n/a"
        idr = f"Rp{q.idr:,.0f}" if isinstance(q.idr, (int, float)) else "n/a"
        chg = f"{q.usd_24h_change:+.2f}%" if isinstance(q.usd_24h_change, (int, float)) else "n/a"
        parts.append(f"Harga {q.symbol} saat ini sekitar {usd} atau {idr}, perubahan 24 jam {chg}.")
        if q.fetched_at:
            timestamps.append(q.fetched_at)

    if not parts:
        return ""
    stamp = _format_market_timestamp(timestamps[0]) if timestamps else ""
    return " ".join(parts) + (f" Data diambil pada {stamp}." if stamp else "")
