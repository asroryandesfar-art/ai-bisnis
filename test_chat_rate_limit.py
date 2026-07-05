"""H-02 — rate limit chat publik berbasis kunci SERVER (anti-spoof), bukan
identitas dari body yang dikontrol klien.
"""
import asyncio
import types

import pytest
from pydantic import ValidationError

import main
from rate_limiter import RateLimiter, LimitStatus


def _fake_request(headers=None, client_host="203.0.113.9"):
    client = types.SimpleNamespace(host=client_host) if client_host else None
    return types.SimpleNamespace(headers=(headers or {}), client=client)


# ── Kunci rate-limit tak bisa dipalsukan lewat body / XFF ───────────────
def test_key_prefers_cf_connecting_ip():
    req = _fake_request({"CF-Connecting-IP": "198.51.100.7"})
    assert main._rate_limit_client_key(req) == "ip:198.51.100.7"


def test_key_ignores_spoofable_x_forwarded_for():
    # Klien menyuntik X-Forwarded-For -> HARUS diabaikan; fallback ke IP koneksi.
    req = _fake_request({"X-Forwarded-For": "1.2.3.4, 5.6.7.8"}, client_host="203.0.113.9")
    key = main._rate_limit_client_key(req)
    assert key == "ip:203.0.113.9"
    assert "1.2.3.4" not in key


def test_key_does_not_depend_on_body_userid():
    # Dua request dari IP sama tapi userId beda -> kunci rate-limit TETAP sama,
    # jadi rotasi userId tidak lagi melewati limit.
    req = _fake_request({"CF-Connecting-IP": "198.51.100.7"})
    assert main._rate_limit_client_key(req) == main._rate_limit_client_key(req)


# ── RateLimiter benar-benar memblok saat kunci sama dispam ──────────────
def test_same_ip_gets_blocked_after_burst():
    rl = RateLimiter()
    key = "ip:198.51.100.20"
    statuses = [
        asyncio.run(rl.check(user_id=key, bot_id="bot-1", org_id="org-1", agent="supervisor")).status
        for _ in range(9)
    ]
    assert LimitStatus.BLOCKED in statuses, statuses


def test_different_ips_are_tracked_separately():
    rl = RateLimiter()
    # IP A dispam sampai blocked
    for _ in range(9):
        asyncio.run(rl.check(user_id="ip:10.0.0.1", bot_id="b", org_id="org-1", agent="supervisor"))
    # IP B (org sama) request pertama harus TIDAK langsung blocked oleh limit user IP A
    res_b = asyncio.run(rl.check(user_id="ip:10.0.0.2", bot_id="b", org_id="org-2", agent="supervisor"))
    assert res_b.status != LimitStatus.BLOCKED


# ── Input size dibatasi server-side (pydantic) ──────────────────────────
def test_chat_message_length_capped():
    main.ChatReq(message="x" * 2000)  # batas atas OK
    with pytest.raises(ValidationError):
        main.ChatReq(message="x" * 2001)
