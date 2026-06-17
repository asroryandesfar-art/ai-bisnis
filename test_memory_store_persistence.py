"""
MemoryStore persists to a local JSON file (data/memory.json) shared by
every process running BotNesia (e.g. multiple uvicorn workers). Each
process has its OWN MemoryStore singleton in memory, so a naive
"dump my whole in-memory state to the file" save() would let one process
silently clobber facts another process just wrote (lost update), and a
non-atomic write() could leave a half-written/corrupt JSON file behind if
interrupted mid-write.

These tests exercise MemoryStore directly (not via MemoryAgent/LLM) against
real files on disk -- no mocks needed, this is pure file I/O logic.
"""
import json
import os

import pytest

from memory_agent import MemoryStore


def test_two_independent_stores_writing_different_users_dont_clobber_each_other(tmp_path):
    """Simulates two separate worker processes, each with their own
    MemoryStore singleton, both backed by the same persist_path."""
    persist_path = tmp_path / "memory.json"

    store_a = MemoryStore(persist_path=str(persist_path))
    store_a.set_fact("user-a", "org-1", "bot-1", "name", "Asrori")

    # store_b is constructed AFTER store_a's save, so it loads store_a's
    # write -- but even if it didn't, the merge-on-save logic in _save()
    # must re-read the file under lock before writing, so store_b setting
    # a fact for a DIFFERENT user must not erase user-a's fact.
    store_b = MemoryStore(persist_path=str(persist_path))
    store_b.set_fact("user-b", "org-1", "bot-1", "business_type", "toko baju")

    on_disk = json.loads(persist_path.read_text())
    profiles = on_disk["profiles"]
    assert len(profiles) == 2, profiles

    facts_by_user = {p["user_id"]: p["facts"] for p in profiles.values()}
    assert "name" in facts_by_user["user-a"]
    assert facts_by_user["user-a"]["name"]["value"] == "Asrori"
    assert "business_type" in facts_by_user["user-b"]
    assert facts_by_user["user-b"]["business_type"]["value"] == "toko baju"


def test_save_merges_with_disk_even_when_in_memory_store_is_stale(tmp_path):
    """store_a doesn't reload after store_b writes -- store_a's next save()
    must still preserve store_b's fact instead of overwriting the file with
    only what store_a itself knows about."""
    persist_path = tmp_path / "memory.json"

    store_a = MemoryStore(persist_path=str(persist_path))
    store_b = MemoryStore(persist_path=str(persist_path))

    store_a.set_fact("user-a", "org-1", "bot-1", "name", "Asrori")
    store_b.set_fact("user-b", "org-1", "bot-1", "business_type", "toko baju")
    # store_a never reloaded -- it doesn't know user-b exists in memory.
    assert "user-b" not in {p.user_id for p in store_a._long.values()}

    # store_a saves again (e.g. updating its own fact) -- must not erase user-b.
    store_a.set_fact("user-a", "org-1", "bot-1", "city", "Gresik")

    on_disk = json.loads(persist_path.read_text())
    user_ids = {p["user_id"] for p in on_disk["profiles"].values()}
    assert user_ids == {"user-a", "user-b"}


def test_atomic_write_leaves_no_partial_file_on_failure(tmp_path, monkeypatch):
    persist_path = tmp_path / "memory.json"
    store = MemoryStore(persist_path=str(persist_path))
    store.set_fact("user-a", "org-1", "bot-1", "name", "Asrori")
    original_content = persist_path.read_text()

    def _boom(*args, **kwargs):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(os, "fsync", _boom)
    with pytest.raises(OSError):
        store._atomic_write({"profiles": {}, "conversation_summaries": {}})

    # Original file must be untouched (os.replace never ran), and no leftover .tmp files.
    assert persist_path.read_text() == original_content
    leftover_tmp = list(tmp_path.glob(".*.tmp"))
    assert leftover_tmp == [], leftover_tmp


def test_conversation_summaries_also_merge_across_stores(tmp_path):
    persist_path = tmp_path / "memory.json"
    store_a = MemoryStore(persist_path=str(persist_path))
    store_b = MemoryStore(persist_path=str(persist_path))

    store_a.set_conversation_summary("conv-1", "Diskusi soal harga paket.")
    store_b.set_conversation_summary("conv-2", "Diskusi soal integrasi WhatsApp.")

    on_disk = json.loads(persist_path.read_text())
    assert on_disk["conversation_summaries"] == {
        "conv-1": "Diskusi soal harga paket.",
        "conv-2": "Diskusi soal integrasi WhatsApp.",
    }


def test_load_reads_back_what_was_saved(tmp_path):
    persist_path = tmp_path / "memory.json"
    store_a = MemoryStore(persist_path=str(persist_path))
    store_a.set_fact("user-a", "org-1", "bot-1", "name", "Asrori")
    store_a.set_conversation_summary("conv-1", "ringkasan")

    store_reloaded = MemoryStore(persist_path=str(persist_path))
    profile = store_reloaded.get_profile("user-a", "org-1", "bot-1")
    assert profile.facts["name"].value == "Asrori"
    assert store_reloaded.get_conversation_summary("conv-1") == "ringkasan"
