"""feature_flags.flags — evaluasi feature flag (P0-B).

Fondasi rollout aman: tiap kemampuan baru digate flag → default OFF → canary →
prod, TANPA breaking change. Konsisten dengan pola env yang sudah dipakai repo
(STATE_BACKEND, TASK_RUNTIME, RUN_BACKGROUND_TASKS), diformalkan + rollout
deterministik per-org.

Urutan resolusi `is_enabled(key, org_id)`:
  1. Override proses (set_override) — untuk test & toggle runtime in-process.
  2. Env `FEATURE_<KEY>`  — "on|off|true|false|1|0" | "<pct 0..100>" | "canary:orgA,orgB".
  3. `default` argumen (biasanya False).

Rollout canary deterministik: bucket = sha256(f"{key}:{org_id}") % 100; enabled
bila bucket < pct. Deterministik lintas-worker/restart (org yang sama → keputusan
sama), jadi cocok untuk peluncuran bertahap.

Modul MANDIRI (tak impor main/bn_platform) → aman diuji & dipakai di mana saja.
"""
from __future__ import annotations

import hashlib
import os
import re

# Stage siklus hidup fitur (informational; dipakai untuk dokumentasi/registry).
STAGES = ("dev", "beta", "prod", "canary")

_overrides: dict[str, object] = {}     # key -> bool | int(pct) | set(org_ids)


def _norm_env_key(key: str) -> str:
    return "FEATURE_" + re.sub(r"[^A-Za-z0-9]+", "_", key).strip("_").upper()


def _bucket(key: str, org_id: str | None) -> int:
    h = hashlib.sha256(f"{key}:{org_id or ''}".encode("utf-8")).hexdigest()
    return int(h, 16) % 100


def _coerce(raw: str):
    """Ubah nilai string (env/override) → bool | int(pct) | set(org_ids)."""
    v = (raw or "").strip()
    low = v.lower()
    if low in ("on", "true", "1", "yes", "enabled"):
        return True
    if low in ("off", "false", "0", "no", "disabled", ""):
        return False
    if low.startswith("canary:"):
        return {o.strip() for o in v.split(":", 1)[1].split(",") if o.strip()}
    if re.fullmatch(r"\d{1,3}", low):
        return max(0, min(100, int(low)))     # rollout percent
    return False                              # nilai tak dikenal → OFF (fail-safe)


def _evaluate(value, key: str, org_id: str | None) -> bool:
    """Terapkan nilai flag (bool|int|set) untuk org tertentu."""
    if isinstance(value, bool):
        return value
    if isinstance(value, set):                 # daftar org canary eksplisit
        return org_id is not None and org_id in value
    if isinstance(value, int):                 # rollout persen
        if value >= 100:
            return True
        if value <= 0:
            return False
        return _bucket(key, org_id) < value
    return bool(value)


def is_enabled(key: str, *, org_id: str | None = None, default: bool = False) -> bool:
    """True bila fitur `key` aktif untuk `org_id`. Lihat urutan resolusi di modul."""
    if key in _overrides:
        return _evaluate(_overrides[key], key, org_id)
    env = os.environ.get(_norm_env_key(key))
    if env is not None:
        return _evaluate(_coerce(env), key, org_id)
    return bool(default)


# ── Hook runtime/test ────────────────────────────────────────────────────────
def set_override(key: str, value) -> None:
    """Set flag di proses ini (menang atas env). value: bool | int(pct) |
    iterable(org_ids) | str ("on"/"off"/"<pct>"/"canary:...")."""
    if isinstance(value, str):
        value = _coerce(value)
    elif isinstance(value, (set, list, tuple)):
        value = {str(o) for o in value}
    _overrides[key] = value


def clear_override(key: str) -> None:
    _overrides.pop(key, None)


def clear_all_overrides() -> None:
    _overrides.clear()


def active_overrides() -> dict:
    """Snapshot override proses (introspeksi/observability)."""
    return {k: (sorted(v) if isinstance(v, set) else v) for k, v in _overrides.items()}
