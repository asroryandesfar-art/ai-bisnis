"""Agent 'open' tool — buka URL/folder di perangkat (Computer Access actions).

Memverifikasi tool terdaftar & gagal-aman (tanpa benar-benar meluncurkan apa pun):
target kosong / path tidak ada → success False, tanpa exception.
"""
import asyncio

import botnesia_local_agent as bla


def test_open_tool_registered():
    assert "open" in bla.TOOLS
    assert bla.TOOLS["open"] is bla.tool_open


def test_open_requires_target():
    r = asyncio.run(bla.tool_open({}))
    assert r["success"] is False and "target" in r["error"].lower()


def test_open_missing_path_errors_safely():
    r = asyncio.run(bla.tool_open({"target": "/nonexistent/path/xyz-12345"}))
    assert r["success"] is False   # ditolak guard atau tidak ditemukan, tak crash


def test_open_url_returns_dict():
    # URL tak menyentuh filesystem; Popen bisa gagal di headless → tetap dict, no crash.
    r = asyncio.run(bla.tool_open({"target": "https://example.com"}))
    assert isinstance(r, dict) and "success" in r
