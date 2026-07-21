"""Tests untuk feature_flags (P0-B)."""
import feature_flags as ff


def teardown_function():
    ff.clear_all_overrides()


def test_default_off():
    assert ff.is_enabled("newthing") is False
    assert ff.is_enabled("newthing", default=True) is True


def test_env_on_off(monkeypatch):
    monkeypatch.setenv("FEATURE_MY_FEAT", "on")
    assert ff.is_enabled("my_feat") is True
    monkeypatch.setenv("FEATURE_MY_FEAT", "off")
    assert ff.is_enabled("my_feat") is False


def test_env_key_normalization(monkeypatch):
    # "durable-runtime" / "durable.runtime" → FEATURE_DURABLE_RUNTIME
    monkeypatch.setenv("FEATURE_DURABLE_RUNTIME", "true")
    assert ff.is_enabled("durable-runtime") is True
    assert ff.is_enabled("durable.runtime") is True


def test_override_beats_env(monkeypatch):
    monkeypatch.setenv("FEATURE_X", "off")
    ff.set_override("x", True)
    assert ff.is_enabled("x") is True
    ff.clear_override("x")
    assert ff.is_enabled("x") is False


def test_canary_explicit_orgs():
    ff.set_override("beta", "canary:org1,org2")
    assert ff.is_enabled("beta", org_id="org1") is True
    assert ff.is_enabled("beta", org_id="org3") is False
    assert ff.is_enabled("beta", org_id=None) is False


def test_rollout_percent_deterministic():
    ff.set_override("roll", 50)
    # deterministik: org yang sama → keputusan yang sama, lintas panggilan
    first = ff.is_enabled("roll", org_id="orgA")
    assert ff.is_enabled("roll", org_id="orgA") is first
    # 0% → semua OFF, 100% → semua ON
    ff.set_override("roll", 0)
    assert ff.is_enabled("roll", org_id="orgA") is False
    ff.set_override("roll", 100)
    assert ff.is_enabled("roll", org_id="orgA") is True


def test_rollout_distribution_roughly_matches_percent():
    ff.set_override("dist", 30)
    orgs = [f"org{i}" for i in range(2000)]
    on = sum(1 for o in orgs if ff.is_enabled("dist", org_id=o))
    ratio = on / len(orgs)
    assert 0.25 <= ratio <= 0.35        # ~30% ± toleransi hashing


def test_unknown_env_value_is_off(monkeypatch):
    monkeypatch.setenv("FEATURE_WEIRD", "maybe")
    assert ff.is_enabled("weird") is False


def test_active_overrides_snapshot():
    ff.set_override("a", True)
    ff.set_override("b", "canary:x,y")
    snap = ff.active_overrides()
    assert snap["a"] is True
    assert snap["b"] == ["x", "y"]
