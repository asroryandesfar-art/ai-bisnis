"""Tests untuk file_system_service.py"""
import os
import tempfile
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from file_system_service import FileSystemService, _safe_path, _is_text_file, TEXT_EXTENSIONS


# ── Pure function tests ────────────────────────────────────────────────────────

class TestSafePath:
    def test_valid_path_returns_resolved(self):
        p, err = _safe_path("/tmp/test.txt")
        assert p is not None
        assert err == ""

    def test_etc_passwd_blocked(self):
        p, err = _safe_path("/etc/passwd")
        assert p is None
        assert "diblokir" in err.lower() or "blocked" in err.lower() or "keamanan" in err.lower()

    def test_proc_blocked(self):
        p, err = _safe_path("/proc/version")
        assert p is None

    def test_path_outside_base_blocked(self):
        p, err = _safe_path("/tmp/outside/file.txt", allowed_base="/home/user/project")
        assert p is None
        assert "luar" in err or "outside" in err

    def test_invalid_path_returns_error(self):
        p, err = _safe_path("")
        # Empty path resolves to cwd — acceptable (no error) or might fail
        # Either way, function must not raise
        assert isinstance(err, str)


class TestIsTextFile:
    def test_py_is_text(self, tmp_path):
        f = tmp_path / "script.py"
        f.write_text("print('hello')")
        assert _is_text_file(f) is True

    def test_ts_is_text(self, tmp_path):
        f = tmp_path / "app.ts"
        f.write_text("const x = 1;")
        assert _is_text_file(f) is True

    def test_png_not_text(self, tmp_path):
        f = tmp_path / "image.png"
        f.write_bytes(b"\x89PNG\r\n")
        assert _is_text_file(f) is False

    def test_json_is_text(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text('{"key": "val"}')
        assert _is_text_file(f) is True


# ── Service tests (mock permission, real filesystem) ──────────────────────────

def _make_service(tmp_path, allowed=True):
    mock_pool = AsyncMock()
    mock_pm = AsyncMock()
    grant_id = "mock-grant-id" if allowed else None
    mock_pm.check = AsyncMock(return_value={"allowed": allowed, "mode": "allow_always", "grant_id": grant_id})

    from file_system_service import FileSystemService
    svc = FileSystemService(
        mock_pool, "test-org", mock_pm,
        allowed_base_dir=str(tmp_path),
    )
    return svc


@pytest.mark.asyncio
async def test_read_file_success(tmp_path):
    target = tmp_path / "hello.txt"
    target.write_text("Hello World!")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.read_file(str(target))

    assert result["success"] is True
    assert "Hello World!" in result["content"]
    assert result["type"] == "text"


@pytest.mark.asyncio
async def test_read_file_not_found(tmp_path):
    svc = _make_service(tmp_path, allowed=True)
    result = await svc.read_file(str(tmp_path / "nonexistent.txt"))

    assert result["success"] is False
    assert "tidak ditemukan" in result["error"].lower() or "not found" in result["error"].lower()


@pytest.mark.asyncio
async def test_read_file_denied_without_permission(tmp_path):
    target = tmp_path / "secret.txt"
    target.write_text("secret")

    svc = _make_service(tmp_path, allowed=False)
    result = await svc.read_file(str(target))

    assert result["success"] is False
    assert "requires_permission" in result
    assert result["requires_permission"] == "read_files"


@pytest.mark.asyncio
async def test_write_file_success(tmp_path):
    svc = _make_service(tmp_path, allowed=True)
    target = str(tmp_path / "new_file.txt")
    result = await svc.write_file(target, "New content here")

    assert result["success"] is True
    assert Path(target).read_text() == "New content here"


@pytest.mark.asyncio
async def test_write_file_no_overwrite_by_default(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("original")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.write_file(str(target), "new content")

    assert result["success"] is False
    assert "overwrite" in result["error"].lower() or "sudah ada" in result["error"].lower()


@pytest.mark.asyncio
async def test_write_file_overwrite_allowed(tmp_path):
    target = tmp_path / "existing.txt"
    target.write_text("original")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.write_file(str(target), "new content", overwrite=True)

    assert result["success"] is True
    assert target.read_text() == "new content"


@pytest.mark.asyncio
async def test_edit_file_success(tmp_path):
    target = tmp_path / "editable.py"
    target.write_text("def hello():\n    return 'world'\n")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.edit_file(str(target), old_text="'world'", new_text="'earth'")

    assert result["success"] is True
    assert "'earth'" in target.read_text()


@pytest.mark.asyncio
async def test_edit_file_text_not_found(tmp_path):
    target = tmp_path / "file.py"
    target.write_text("def foo(): pass\n")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.edit_file(str(target), old_text="NONEXISTENT_TEXT", new_text="bar")

    assert result["success"] is False
    assert "tidak ditemukan" in result["error"].lower()


@pytest.mark.asyncio
async def test_delete_file_requires_confirmation(tmp_path):
    target = tmp_path / "delete_me.txt"
    target.write_text("bye")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.delete_file(str(target), confirmed=False)

    assert result["success"] is False
    assert "requires_confirmation" in result.get("status", "")
    assert target.exists()  # File TIDAK dihapus


@pytest.mark.asyncio
async def test_delete_file_confirmed(tmp_path):
    target = tmp_path / "delete_me.txt"
    target.write_text("bye")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.delete_file(str(target), confirmed=True)

    assert result["success"] is True
    assert not target.exists()


@pytest.mark.asyncio
async def test_list_directory(tmp_path):
    (tmp_path / "a.py").write_text("a")
    (tmp_path / "b.ts").write_text("b")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.list_directory(str(tmp_path))

    assert result["success"] is True
    names = {e["name"] for e in result["entries"]}
    assert "a.py" in names
    assert "b.ts" in names


@pytest.mark.asyncio
async def test_search_files(tmp_path):
    (tmp_path / "match.py").write_text("UNIQUE_SEARCH_TOKEN_XYZ")
    (tmp_path / "nomatch.py").write_text("nothing here")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.search_files(str(tmp_path), query="UNIQUE_SEARCH_TOKEN_XYZ")

    assert result["success"] is True
    assert any("match.py" in r["path"] for r in result["results"])


@pytest.mark.asyncio
async def test_compress_and_extract(tmp_path):
    src = tmp_path / "tosync"
    src.mkdir()
    (src / "file.txt").write_text("test content")

    zip_out = str(tmp_path / "archive.zip")
    svc = _make_service(tmp_path, allowed=True)

    compress_result = await svc.compress(str(src), output_zip=zip_out)
    assert compress_result["success"] is True
    assert Path(zip_out).exists()

    extract_dest = str(tmp_path / "extracted")
    extract_result = await svc.extract(zip_out, dest=extract_dest)
    assert extract_result["success"] is True
    assert Path(extract_dest).exists()


@pytest.mark.asyncio
async def test_understand_project(tmp_path):
    (tmp_path / "main.py").write_text("print('hello')")
    (tmp_path / "requirements.txt").write_text("fastapi")
    sub = tmp_path / "src"
    sub.mkdir()
    (sub / "app.ts").write_text("const x = 1;")

    svc = _make_service(tmp_path, allowed=True)
    result = await svc.understand_project(str(tmp_path))

    assert result["success"] is True
    assert result["total_files"] >= 3
    assert ".py" in result["top_extensions"] or ".ts" in result["top_extensions"]
    assert any("requirements.txt" in ep or "main.py" in ep for ep in result["entrypoints"])
