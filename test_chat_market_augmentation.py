"""Unit test for _build_market_augmentation (chat handler decomposition step 1).

Verifies the extracted market-data helper: no-op for non-price queries, and
augments the system prompt + returns a market answer for price queries (market
fetchers mocked, no real API).
"""
import asyncio

import main


def test_non_price_query_is_noop():
    system_in = "You are an assistant."
    system_out, market_answer = asyncio.run(
        main._build_market_augmentation("apa kabar?", system_in, "id")
    )
    assert system_out == system_in
    assert market_answer == ""


def test_price_query_augments_system_and_returns_answer(monkeypatch):
    async def _crypto(_q, **k):
        return ["BTC"]

    async def _stock(_q, **k):
        return []

    monkeypatch.setattr(main, "looks_like_market_price_query", lambda t: True)
    monkeypatch.setattr(main, "fetch_crypto_quotes", _crypto)
    monkeypatch.setattr(main, "fetch_stock_quotes", _stock)
    monkeypatch.setattr(main, "combine_market_answers", lambda c, s: "BTC is $100k")
    monkeypatch.setattr(main, "build_crypto_market_context", lambda q: "CRYPTO CTX")
    monkeypatch.setattr(main, "build_stock_market_context", lambda q: "")

    system_out, market_answer = asyncio.run(
        main._build_market_augmentation("harga btc?", "SYS", "id")
    )
    assert market_answer == "BTC is $100k"
    assert "CRYPTO CTX" in system_out
    assert "Data pasar finansial" in system_out  # Indonesian title


def test_price_query_english_title(monkeypatch):
    async def _crypto(_q, **k):
        return ["BTC"]

    async def _stock(_q, **k):
        return []

    monkeypatch.setattr(main, "looks_like_market_price_query", lambda t: True)
    monkeypatch.setattr(main, "fetch_crypto_quotes", _crypto)
    monkeypatch.setattr(main, "fetch_stock_quotes", _stock)
    monkeypatch.setattr(main, "combine_market_answers", lambda c, s: "answer")
    monkeypatch.setattr(main, "build_crypto_market_context", lambda q: "CTX")
    monkeypatch.setattr(main, "build_stock_market_context", lambda q: "")

    system_out, _ = asyncio.run(main._build_market_augmentation("btc price?", "SYS", "en"))
    assert "Financial market data" in system_out


def test_fetch_failure_degrades_gracefully(monkeypatch):
    async def _boom(_q, **k):
        raise RuntimeError("provider down")

    monkeypatch.setattr(main, "looks_like_market_price_query", lambda t: True)
    monkeypatch.setattr(main, "fetch_crypto_quotes", _boom)
    monkeypatch.setattr(main, "fetch_stock_quotes", _boom)

    system_out, market_answer = asyncio.run(
        main._build_market_augmentation("harga btc?", "SYS", "id")
    )
    assert system_out == "SYS"  # unchanged on failure
    assert market_answer == ""
