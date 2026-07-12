"""Unit test untuk leader gate background task (Phase 1: horizontal scaling).

Memastikan loop in-process (Gmail poller, intelligence learning, Meta refresh)
hanya jalan bila replika ini leader (RUN_BACKGROUND_TASKS). Diuji lewat titik
keputusan tunggal should_run_background_tasks(), tanpa boot server.
"""
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
