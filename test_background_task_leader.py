"""Unit test untuk leader gate background task (Phase 1: horizontal scaling).

Memastikan loop in-process (Gmail poller, intelligence learning, Meta refresh)
hanya jalan bila replika ini leader. Path flag (RUN_BACKGROUND_TASKS) diuji lewat
should_run_background_tasks(); path leader election otomatis lewat
resolve_background_leadership() + try_acquire_leadership() (pg_try_advisory_lock).
"""
import asyncio

import asyncpg

import main


def test_defaults_to_leader_for_single_instance():
    # Default harus True supaya deploy single-instance tak berubah perilaku.
    assert main.cfg.run_background_tasks is True
    assert main.should_run_background_tasks() is True


def test_disabled_when_flag_off(monkeypatch):
    monkeypatch.setattr(main.cfg, "run_background_tasks", False)
    assert main.should_run_background_tasks() is False


def test_enabled_when_flag_on(monkeypatch):
    monkeypatch.setattr(main.cfg, "run_background_tasks", True)
    assert main.should_run_background_tasks() is True


def test_env_var_binds(monkeypatch):
    monkeypatch.setenv("RUN_BACKGROUND_TASKS", "0")
    assert main.Settings().run_background_tasks is False


# ── Leader election otomatis (pg_try_advisory_lock) ──────────────────────────

def test_leader_election_defaults_off():
    # Default harus False supaya perilaku flag lama tidak berubah.
    assert main.Settings().db_leader_election is False


def test_leader_election_env_binds(monkeypatch):
    monkeypatch.setenv("DB_LEADER_ELECTION", "1")
    assert main.Settings().db_leader_election is True


def test_resolve_uses_flag_when_election_off(monkeypatch):
    # election OFF → jatuh ke flag, TIDAK menyentuh advisory lock.
    monkeypatch.setattr(main.cfg, "db_leader_election", False)
    monkeypatch.setattr(main.cfg, "run_background_tasks", False)

    async def _boom():
        raise AssertionError("try_acquire_leadership tidak boleh dipanggil saat election off")

    monkeypatch.setattr(main, "try_acquire_leadership", _boom)
    assert asyncio.run(main.resolve_background_leadership()) is False


def test_resolve_uses_advisory_lock_when_election_on(monkeypatch):
    # election ON → hasil ditentukan try_acquire_leadership (flag diabaikan).
    monkeypatch.setattr(main.cfg, "db_leader_election", True)
    monkeypatch.setattr(main.cfg, "run_background_tasks", False)

    async def _win():
        return True

    monkeypatch.setattr(main, "try_acquire_leadership", _win)
    assert asyncio.run(main.resolve_background_leadership()) is True


def test_advisory_lock_is_exclusive(monkeypatch):
    # Saat lock sudah dipegang koneksi lain, replika ini kalah election.
    monkeypatch.setattr(main, "_leader_conn", None)

    async def _run():
        holder = await asyncpg.connect(main.cfg.database_url.replace("+asyncpg", ""))
        try:
            got = await holder.fetchval(
                "SELECT pg_try_advisory_lock($1)", main._LEADER_ADVISORY_LOCK_KEY
            )
            assert got is True  # holder eksternal memegang lock
            assert await main.try_acquire_leadership() is False
            assert main._leader_conn is None  # tidak menahan koneksi saat kalah
        finally:
            await holder.close()  # lepas lock eksternal

    asyncio.run(_run())


def test_acquire_and_release_leadership(monkeypatch):
    # Tanpa holder lain: menang, menahan koneksi, lalu melepas saat release.
    monkeypatch.setattr(main, "_leader_conn", None)

    async def _run():
        assert await main.try_acquire_leadership() is True
        assert main._leader_conn is not None
        # Idempoten: panggilan kedua langsung True tanpa koneksi baru.
        conn1 = main._leader_conn
        assert await main.try_acquire_leadership() is True
        assert main._leader_conn is conn1
        await main.release_leadership()
        assert main._leader_conn is None

    asyncio.run(_run())
