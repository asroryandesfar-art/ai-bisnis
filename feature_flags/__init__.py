"""feature_flags — feature flag / gradual rollout untuk BotNesia (P0-B).

Gate tiap kemampuan baru: default OFF → canary (per-org, deterministik) → prod,
tanpa breaking change. Contoh:

    from feature_flags import is_enabled
    if is_enabled("durable_runtime", org_id=org):
        ...   # jalur baru
    else:
        ...   # jalur lama (default)

Kontrol via env `FEATURE_DURABLE_RUNTIME=on|off|<pct>|canary:orgA,orgB`, atau
`set_override()` untuk test/runtime. Lihat feature_flags/flags.py + ADR-0002.
"""
from feature_flags.flags import (
    STAGES,
    is_enabled,
    set_override,
    clear_override,
    clear_all_overrides,
    active_overrides,
)

__all__ = [
    "STAGES", "is_enabled", "set_override", "clear_override",
    "clear_all_overrides", "active_overrides",
]
