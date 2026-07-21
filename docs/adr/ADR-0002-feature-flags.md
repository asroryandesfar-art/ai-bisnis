# ADR-0002 — Feature Flags (`feature_flags`)

- **Status:** Accepted — implementasi awal selesai (env + override + rollout); DB-runtime menyusul
- **Tanggal:** 2026-07-22
- **Konteks fase:** Fase 1 Fondasi Platform, item **P0-B**
- **Terkait:** ADR-0001 (shared state), rollout P0-C/P0-D

## Konteks
Aturan platform: **tiap kemampuan baru wajib digate** (Development/Beta/Production/
Canary) agar rollout aman & reversible tanpa breaking change. Repo sudah memakai
pola env ad-hoc (`STATE_BACKEND`, `TASK_RUNTIME`, `RUN_BACKGROUND_TASKS`) tapi tanpa
standar, tanpa rollout bertahap per-org, tanpa introspeksi.

## Keputusan
Modul mandiri `feature_flags` dengan `is_enabled(key, *, org_id=None, default=False)`.
Resolusi: **override proses** (`set_override`, untuk test/runtime) → **env**
`FEATURE_<KEY>` (`on|off|<pct>|canary:orgA,orgB`) → **default** (biasanya OFF).
Rollout canary **deterministik**: `sha256(f"{key}:{org_id}") % 100 < pct` → org yang
sama selalu dapat keputusan sama (aman untuk peluncuran bertahap lintas worker/restart).

## Alternatif
1. **Lib eksternal (LaunchDarkly/Unleash).** Ditolak: dependency/biaya/SaaS untuk kebutuhan yang kecil.
2. **Env mentah tanpa modul.** Ditolak: tak ada rollout per-org, tak ada override test, tak konsisten.
3. **Modul env+rollout (DIPILIH).** Risiko terkecil (additive, default OFF), maintainable, nol dependency, deterministik.

## Konsekuensi
**Positif:** semua fitur baru bisa digate seragam + canary per-org; reversible (ubah env/hapus flag); deterministik & testable.
**Batasan (jujur):** flag env butuh restart untuk berubah. **Follow-up:** layer DB-backed
(`feature_flags` tabel + StateStore cache + endpoint admin RBAC + audit) untuk toggle
runtime tanpa redeploy — additive di atas API `is_enabled` yang sama.

## Pemakaian (konsumen berikutnya)
```python
from feature_flags import is_enabled
if is_enabled("durable_runtime", org_id=org):
    await enqueue_durable_job(...)      # jalur baru (P0-D)
else:
    result = await agent.run_task(...)  # jalur lama (default)
```

## Rollback
Hapus/`off` flag → jalur lama. Modul bisa idle tanpa efek (zero wiring saat ini).

## Status implementasi
- ✅ core: `is_enabled` (env + override + rollout deterministik + stages) + 9 test.
- ⏳ DB-runtime flags + admin API + UI (follow-up additive).
- Konsumen pertama: canary P0-C/P0-D.
