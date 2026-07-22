"""task_runtime.monitor — agregasi observability durable runtime (P2-C).

Read-only atas `agent_jobs` (P0-D) & `task_evaluations` (P1-D) → snapshot sehat
antrian/worker + tren skor untuk dashboard operator realtime. Org-scoped, tanpa
skema baru. Bagian evaluasi fail-open (tabel absen → nol) agar tak pernah 500.
"""
from __future__ import annotations

from perf_cache import TTLCache, get_or_compute

# Semua status agent_jobs (CHECK constraint) — dipakai agar dict antrian selalu
# lengkap (status tanpa baris → 0), bukan sekadar yang kebetulan ada.
_JOB_STATUSES = (
    "queued", "running", "paused", "pausing", "cancelling",
    "cancelled", "failed", "dead_letter", "completed",
)


class RuntimeMonitor:
    """Agregat metrik durable runtime untuk satu org.

    `cache_ttl_s>0` (P2-D) → hasil snapshot/tren di-cache per (org, window) selama
    TTL detik → koneksi SSE yang mem-poll TAK memukul DB tiap tick (banyak operator
    streaming = 1 query per TTL, bukan N). Default 0 = tanpa cache (byte-identik)."""

    def __init__(self, *, cache_ttl_s: float = 0.0):
        self._cache_ttl = float(cache_ttl_s)
        self._cache = TTLCache(maxsize=4096)

    async def health_snapshot(self, pool, org_id: str, *, window_hours: int = 24) -> dict:
        window_hours = max(1, min(720, int(window_hours)))
        return await get_or_compute(
            self._cache, ("health", org_id, window_hours), self._cache_ttl,
            lambda: self._health_snapshot(pool, org_id, window_hours),
        )

    async def _health_snapshot(self, pool, org_id: str, window_hours: int) -> dict:
        by_status = {s: 0 for s in _JOB_STATUSES}
        for r in await pool.fetch(
            "SELECT status, COUNT(*)::int AS n FROM agent_jobs WHERE org_id=$1 GROUP BY status",
            org_id,
        ):
            by_status[r["status"]] = r["n"]

        derived = await pool.fetchrow(
            """SELECT
                 COUNT(*) FILTER (WHERE status='running' AND lease_until > NOW())::int AS in_flight,
                 COUNT(*) FILTER (WHERE status IN ('running','pausing','cancelling')
                                  AND (lease_until IS NULL OR lease_until <= NOW()))::int AS stalled,
                 COUNT(*) FILTER (WHERE status='completed'
                                  AND updated_at >= NOW() - INTERVAL '1 hour')::int AS completed_1h,
                 COUNT(*) FILTER (WHERE status='failed'
                                  AND updated_at >= NOW() - INTERVAL '1 hour')::int AS failed_1h,
                 COUNT(*) FILTER (WHERE status='completed'
                                  AND updated_at >= NOW() - make_interval(hours => $2::int))::int AS completed_window,
                 COUNT(*) FILTER (WHERE status='failed'
                                  AND updated_at >= NOW() - make_interval(hours => $2::int))::int AS failed_window
               FROM agent_jobs WHERE org_id=$1""",
            org_id, window_hours,
        )

        workers = await pool.fetch(
            """SELECT lease_owner,
                      COUNT(*)::int AS active_jobs,
                      MAX(lease_until) AS lease_until
               FROM agent_jobs
               WHERE org_id=$1 AND lease_owner IS NOT NULL
                     AND lease_until > NOW() AND status='running'
               GROUP BY lease_owner ORDER BY active_jobs DESC""",
            org_id,
        )

        d = dict(derived or {})
        done = int(d.get("completed_window", 0)) + int(d.get("failed_window", 0))
        success_rate = (100.0 * int(d.get("completed_window", 0)) / done) if done else 0.0
        return {
            "window_hours": window_hours,
            "queue": by_status,
            "backlog": by_status["queued"],
            "in_flight": int(d.get("in_flight", 0)),
            "stalled": int(d.get("stalled", 0)),        # lease kedaluwarsa → kandidat recovery
            "dead_letter": by_status["dead_letter"],
            "throughput": {
                "completed_1h": int(d.get("completed_1h", 0)),
                "failed_1h": int(d.get("failed_1h", 0)),
                "completed_window": int(d.get("completed_window", 0)),
                "failed_window": int(d.get("failed_window", 0)),
                "success_rate": round(success_rate, 2),
            },
            "workers": [dict(w) for w in workers],
            "evaluation": await self._eval_summary(pool, org_id, window_hours),
        }

    async def _eval_summary(self, pool, org_id: str, window_hours: int) -> dict:
        try:
            r = await pool.fetchrow(
                """SELECT COALESCE(AVG(overall),0)::float AS avg_overall,
                          COUNT(*)::int AS n,
                          COALESCE(100.0*COUNT(*) FILTER (WHERE judged)/NULLIF(COUNT(*),0),0)::float AS judged_pct
                   FROM task_evaluations
                   WHERE org_id=$1 AND created_at >= NOW() - make_interval(hours => $2::int)""",
                org_id, window_hours,
            )
            d = dict(r or {})
            return {"avg_overall": round(float(d.get("avg_overall") or 0.0), 4),
                    "count": int(d.get("n", 0)),
                    "judged_pct": round(float(d.get("judged_pct") or 0.0), 2)}
        except Exception:
            return {"avg_overall": 0.0, "count": 0, "judged_pct": 0.0}

    async def evaluation_trends(self, pool, org_id: str, *, window_hours: int = 24) -> list[dict]:
        """Skor Evaluation per-agen (rata-rata/min/max/jumlah/%judged) dalam window."""
        window_hours = max(1, min(720, int(window_hours)))
        return await get_or_compute(
            self._cache, ("trends", org_id, window_hours), self._cache_ttl,
            lambda: self._evaluation_trends(pool, org_id, window_hours),
        )

    async def _evaluation_trends(self, pool, org_id: str, window_hours: int) -> list[dict]:
        try:
            rows = await pool.fetch(
                """SELECT agent_name,
                          COUNT(*)::int AS n,
                          COALESCE(AVG(overall),0)::float AS avg_overall,
                          COALESCE(MIN(overall),0)::float AS min_overall,
                          COALESCE(MAX(overall),0)::float AS max_overall,
                          COALESCE(100.0*COUNT(*) FILTER (WHERE judged)/NULLIF(COUNT(*),0),0)::float AS judged_pct,
                          MAX(created_at) AS last_at
                   FROM task_evaluations
                   WHERE org_id=$1 AND created_at >= NOW() - make_interval(hours => $2::int)
                   GROUP BY agent_name ORDER BY n DESC, agent_name""",
                org_id, window_hours,
            )
            out = []
            for r in rows:
                d = dict(r)
                for k in ("avg_overall", "min_overall", "max_overall", "judged_pct"):
                    d[k] = round(float(d[k]), 4)
                out.append(d)
            return out
        except Exception:
            return []
