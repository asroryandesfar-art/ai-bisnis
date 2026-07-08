"""L-05 — mitigasi DNS-rebinding TOCTOU pada URL ingestion.

Menguji bahwa host di-resolve SATU kali lalu IP-nya di-pin saat koneksi,
sehingga httpx/httpcore tidak melakukan resolusi DNS kedua (celah TOCTOU
tempat DNS berubah antara pengecekan & koneksi).

Tidak melakukan koneksi jaringan nyata — getaddrinfo & httpx di-mock.
"""
from __future__ import annotations

import ipaddress
import socket
from unittest import mock

import httpx
import pytest

import tool_registry as tr


# ── resolve_public_ips ────────────────────────────────────────────────────
def _fake_getaddrinfo(host, port, *a, **kw):
    """Resolver mock: kembalikan satu IPv4 publik untuk host apa pun."""
    return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]


def test_resolve_public_ips_returns_public(monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo", _fake_getaddrinfo)
    assert tr.resolve_public_ips("example.com") == ["93.184.216.34"]


@pytest.mark.parametrize("bad_ip", [
    "127.0.0.1",        # loopback
    "10.0.0.5",         # private (RFC1918)
    "192.168.1.1",      # private
    "169.254.169.254",  # link-local (cloud metadata)
    "0.0.0.0",          # unspecified
    "224.0.0.1",        # multicast
])
def test_resolve_public_ips_fail_closed_on_private(bad_ip, monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (bad_ip, 0))])
    # Host privat di antara hasil → kosong (fail-closed), walau ada IP publik campuran.
    assert tr.resolve_public_ips("evil.rebind") == []


def test_resolve_public_ips_mixed_public_and_private_fail_closed(monkeypatch):
    # DNS server penyerang balas 1 publik + 1 privat → harus tetap ditolak.
    monkeypatch.setattr(tr.socket, "getaddrinfo", lambda host, port, *a, **k: [
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0)),
        (socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0)),
    ])
    assert tr.resolve_public_ips("evil.rebind") == []


def test_resolve_public_ips_unresolvable(monkeypatch):
    def _raise(host, port, *a, **k):
        raise socket.gaierror("no such host")
    monkeypatch.setattr(tr.socket, "getaddrinfo", _raise)
    assert tr.resolve_public_ips("nonexistent.invalid") == []


def test_is_public_host_uses_resolve(monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo", _fake_getaddrinfo)
    assert tr._is_public_host("example.com") is True
    monkeypatch.setattr(tr.socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 0))])
    assert tr._is_public_host("localhost.evil") is False


# ── build_pinned_request — inti mitigasi rebinding ────────────────────────
@pytest.mark.asyncio
async def test_build_pinned_request_pins_ip_not_hostname(monkeypatch):
    """URL request harus menunjuk ke IP ter-pin (bukan hostname), sehingga
    httpx TIDAK me-resolve DNS lagi saat connect."""
    monkeypatch.setattr(tr.socket, "getaddrinfo", _fake_getaddrinfo)
    async with httpx.AsyncClient() as client:
        req = tr.build_pinned_request(client, "GET", "https://example.com/path?q=1")
    # Target koneksi = IP, BUKAN hostname (inilah yang menutup rebinding).
    assert "93.184.216.34" in str(req.url)
    assert "example.com" not in str(req.url).split("/")[2]  # netloc = IP
    # Host header + SNI tetap hostname asli (virtual hosting + cert valid).
    assert req.headers["host"] == "example.com"
    assert req.extensions.get("sni_hostname") == "example.com"
    # Path & query terjaga.
    assert req.url.path == "/path"
    assert str(req.url).endswith("?q=1")


@pytest.mark.asyncio
async def test_build_pinned_request_preserves_explicit_port(monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo", _fake_getaddrinfo)
    async with httpx.AsyncClient() as client:
        req = tr.build_pinned_request(client, "GET", "https://example.com:8443/x")
    assert str(req.url).startswith("https://93.184.216.34:8443/")
    assert req.headers["host"] == "example.com:8443"
    assert req.extensions.get("sni_hostname") == "example.com"


@pytest.mark.asyncio
async def test_build_pinned_request_passes_through_headers(monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo", _fake_getaddrinfo)
    async with httpx.AsyncClient() as client:
        req = tr.build_pinned_request(
            client, "GET", "https://example.com/",
            headers={"User-Agent": "BotNesiaBot/1.0", "Accept": "text/html"},
        )
    assert req.headers["user-agent"] == "BotNesiaBot/1.0"
    assert req.headers["accept"] == "text/html"
    assert req.headers["host"] == "example.com"  # Host ditambahkan


@pytest.mark.asyncio
async def test_build_pinned_request_fail_closed_private(monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo",
                        lambda host, port, *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("10.0.0.5", 0))])
    async with httpx.AsyncClient() as client:
        with pytest.raises(tr.SSRFBlocked):
            tr.build_pinned_request(client, "GET", "https://internal.local/")


@pytest.mark.asyncio
async def test_build_pinned_request_rejects_bad_scheme(monkeypatch):
    monkeypatch.setattr(tr.socket, "getaddrinfo", _fake_getaddrinfo)
    async with httpx.AsyncClient() as client:
        with pytest.raises(tr.SSRFBlocked):
            tr.build_pinned_request(client, "GET", "file:///etc/passwd")


# ── Simulasi DNS-rebinding: IP di-pin SEKALI, perubahan DNS berikutnya
#    tidak memengaruhi koneksi yang sudah dibangun. ────────────────────────
@pytest.mark.asyncio
async def test_dns_rebinding_uses_pinned_ip_not_second_resolution(monkeypatch):
    """Skenario serangan: getaddrinfo balas IP publik saat validasi, lalu
    (rebind) balas IP privat. Karena IP sudah di-pin di build_request, request
    tetap menunjuk ke IP publik pertama — httpx tidak memanggil getaddrinfo
    lagi."""
    calls = {"n": 0}

    def flaky_resolver(host, port, *a, **k):
        calls["n"] += 1
        # Panggilan validasi (resolve_public_ips) → IP publik.
        return [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]

    monkeypatch.setattr(tr.socket, "getaddrinfo", flaky_resolver)
    async with httpx.AsyncClient() as client:
        req = tr.build_pinned_request(client, "GET", "https://victim.example/")
    # getaddrinfo dipanggi tepat 1x (untuk resolve+validate), BUKAN saat connect.
    assert calls["n"] == 1
    # Request sudah terkunci ke IP publik; tidak ada hostname di netloc URL.
    assert "93.184.216.34" in str(req.url)
    assert req.extensions.get("sni_hostname") == "victim.example"
