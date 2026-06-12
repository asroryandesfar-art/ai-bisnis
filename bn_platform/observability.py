"""
bn_platform/observability.py — Prometheus instrumentation (CPU/RAM/Latency/Error/Token)

Menambahkan endpoint `/metrics` (format teks Prometheus) ke FastAPI `app`
existing TANPA mengubah struktur app — dipasang via:

    from bn_platform.observability import instrument_app, record_token_usage
    instrument_app(app)

Metrik yang diekspos:
  • bn_http_requests_total{method,route,status}        — Counter
  • bn_http_request_duration_seconds{method,route}      — Histogram (latency)
  • bn_http_requests_in_progress{method,route}          — Gauge
  • bn_ai_tokens_total{org_id,model,kind}               — Counter (prompt/completion)
  • bn_ai_requests_total{org_id,agent,status}           — Counter (sukses/gagal AI agent)
  • bn_ai_request_duration_seconds{agent}               — Histogram
  • bn_process_resident_memory_bytes / bn_process_cpu_seconds_total
    — disediakan otomatis oleh ProcessCollector bawaan prometheus_client

Endpoint `/metrics` opsional dilindungi `METRICS_AUTH_TOKEN` (.env) — Prometheus
scrape config cukup menambahkan header `Authorization: Bearer <token>`. Lihat
contoh `prometheus.yml` & dashboard Grafana di `bn_platform/observability_dashboard.json`.

CATATAN CARDINALITY: label `route` memakai `request.scope["route"].path_format`
(template path FastAPI, mis. "/bots/{bot_id}") — BUKAN raw URL — supaya jumlah
seri waktu tetap terbatas meski path mengandung UUID/ID dinamis.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

import time
from typing import Awaitable, Callable

from fastapi import FastAPI, Request, Response
from prometheus_client import (
    CONTENT_TYPE_LATEST,
    CollectorRegistry,
    Counter,
    Gauge,
    Histogram,
    generate_latest,
    multiprocess,
)
import os

from .config import cfg as platform_cfg

# ============================================================
# REGISTRY & METRICS
# ============================================================
# Registry default global cukup untuk deployment single-process (uvicorn --workers 1
# atau setiap worker discrape terpisah lewat sidecar). Untuk multi-process (gunicorn
# dgn banyak worker dlm satu container), set env PROMETHEUS_MULTIPROC_DIR dan
# instrument_app() otomatis beralih ke MultiProcessCollector — lihat docstring
# prometheus_client.multiprocess untuk detail kontrak direktori.

_MULTIPROC_DIR = os.environ.get("PROMETHEUS_MULTIPROC_DIR", "")

HTTP_REQUESTS_TOTAL = Counter(
    "bn_http_requests_total", "Total permintaan HTTP yang diterima",
    ["method", "route", "status"],
)
HTTP_REQUEST_DURATION = Histogram(
    "bn_http_request_duration_seconds", "Distribusi latensi permintaan HTTP (detik)",
    ["method", "route"],
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0),
)
HTTP_REQUESTS_IN_PROGRESS = Gauge(
    "bn_http_requests_in_progress", "Jumlah permintaan HTTP yang sedang diproses",
    ["method", "route"],
)
HTTP_ERRORS_TOTAL = Counter(
    "bn_http_errors_total", "Total respons HTTP dengan status >= 500",
    ["method", "route"],
)

AI_TOKENS_TOTAL = Counter(
    "bn_ai_tokens_total", "Total token yang dipakai pemanggilan LLM",
    ["org_id", "model", "kind"],   # kind: prompt | completion
)
AI_REQUESTS_TOTAL = Counter(
    "bn_ai_requests_total", "Total pemanggilan AI agent",
    ["agent", "status"],          # status: success | error
)
AI_REQUEST_DURATION = Histogram(
    "bn_ai_request_duration_seconds", "Distribusi latensi pemanggilan AI agent (detik)",
    ["agent"],
    buckets=(0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 60.0),
)

DB_POOL_SIZE = Gauge("bn_db_pool_size", "Ukuran connection pool database saat ini")
DB_POOL_IN_USE = Gauge("bn_db_pool_in_use", "Jumlah koneksi database yang sedang dipakai")


# ============================================================
# MIDDLEWARE — instrumentasi otomatis tiap request
# ============================================================

def _route_template(request: Request) -> str:
    route = request.scope.get("route")
    path_format = getattr(route, "path_format", None)
    if path_format:
        return path_format
    # Fallback (mis. 404 sebelum routing match) — pakai path mentah agar tidak
    # silently dropped, risiko cardinality kecil karena 404 biasanya jarang & seragam.
    return request.url.path


async def _metrics_middleware(request: Request, call_next: Callable[[Request], Awaitable[Response]]) -> Response:
    if request.url.path == "/metrics":
        return await call_next(request)

    method = request.method
    start = time.perf_counter()
    # `route` belum tersedia sebelum routing selesai — ambil setelah call_next
    # lalu gunakan template path supaya label tetap berkardinalitas rendah.
    try:
        response = await call_next(request)
    except Exception:
        route = _route_template(request)
        HTTP_ERRORS_TOTAL.labels(method=method, route=route).inc()
        HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status="500").inc()
        HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(time.perf_counter() - start)
        raise

    route = _route_template(request)
    duration = time.perf_counter() - start
    status_code = str(response.status_code)
    HTTP_REQUESTS_TOTAL.labels(method=method, route=route, status=status_code).inc()
    HTTP_REQUEST_DURATION.labels(method=method, route=route).observe(duration)
    if response.status_code >= 500:
        HTTP_ERRORS_TOTAL.labels(method=method, route=route).inc()
    return response


# ============================================================
# HELPER — dipanggil dari pipeline AI agent (agent_api.py / intelligence/*)
# ============================================================

def record_token_usage(*, org_id: str | None, model: str, prompt_tokens: int = 0, completion_tokens: int = 0) -> None:
    """Catat pemakaian token LLM untuk dashboard biaya/kuota per tenant.
    Panggil setelah tiap respons LLM (mis. di intelligence/llm.call_llm wrapper)."""
    org_label = org_id or "unknown"
    if prompt_tokens:
        AI_TOKENS_TOTAL.labels(org_id=org_label, model=model, kind="prompt").inc(prompt_tokens)
    if completion_tokens:
        AI_TOKENS_TOTAL.labels(org_id=org_label, model=model, kind="completion").inc(completion_tokens)


def record_ai_request(*, agent: str, success: bool, duration_seconds: float) -> None:
    """Catat hasil & latensi satu pemanggilan AI agent (mis. SupervisorAgent, FAQAgent)."""
    AI_REQUESTS_TOTAL.labels(agent=agent, status="success" if success else "error").inc()
    AI_REQUEST_DURATION.labels(agent=agent).observe(duration_seconds)


def record_db_pool_stats(*, size: int, in_use: int) -> None:
    """Catat statistik connection pool — panggil berkala (mis. tiap request /healthz
    atau dari Celery beat) karena asyncpg.Pool tidak mengekspos collector sendiri."""
    DB_POOL_SIZE.set(size)
    DB_POOL_IN_USE.set(in_use)


# ============================================================
# /metrics ENDPOINT & WIRING
# ============================================================

def _metrics_response() -> Response:
    if _MULTIPROC_DIR:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry, path=_MULTIPROC_DIR)
        payload = generate_latest(registry)
    else:
        payload = generate_latest()
    return Response(content=payload, media_type=CONTENT_TYPE_LATEST)


def instrument_app(app: FastAPI) -> None:
    """Pasang middleware metrik HTTP + endpoint GET /metrics ke `app` FastAPI existing.
    Panggil sekali di main.py setelah `app = FastAPI(...)` didefinisikan, mis.:

        from bn_platform.observability import instrument_app
        instrument_app(app)
    """
    app.middleware("http")(_metrics_middleware)

    @app.get("/metrics", include_in_schema=False)
    async def metrics(request: Request):
        if platform_cfg.metrics_auth_token:
            auth = request.headers.get("authorization", "")
            expected = f"Bearer {platform_cfg.metrics_auth_token}"
            if auth != expected:
                return Response(status_code=401, content="Unauthorized")
        return _metrics_response()
