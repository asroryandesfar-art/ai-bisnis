# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project follows a
trunk-based, continuously-deployed workflow (no fixed release cadence yet), so
entries are grouped by theme rather than semantic version tags.

## [Unreleased]

### Added — Platform Foundation (Fase 1)
- **Feature flags (`feature_flags`, P0-B)** — standard gate for shipping new capabilities safely
  (default OFF → per-org canary → prod) with no breaking change. `is_enabled(key, org_id=...)`
  resolves process override → env `FEATURE_<KEY>` (`on|off|<pct>|canary:orgA,orgB`) → default.
  Canary rollout is deterministic (`sha256(key:org) % 100 < pct`), so the same org gets a stable
  decision across workers/restarts. Self-contained, zero wiring (consumers adopt it, e.g. P0-C/P0-D
  canary). Env-based today; DB-backed runtime toggles are a documented follow-up. 9 tests, ADR-0002.
- **Event bus (`event_bus`, P0-C)** — in-process publish/subscribe to decouple producers from
  consumers (observability, evaluation, memory) without direct calls. `publish(type, payload)` /
  `subscribe(type, handler)`; sync+async handlers; per-handler error isolation (one failing
  consumer never breaks the publisher or others); wildcard `*`; standardized envelope
  `{id, type, org_id, ts, payload, trace_id}`; typed event constants (TaskStarted/Finished/Failed,
  MemoryUpdated, KnowledgeUpdated, Browser/ScraperFinished, WorkflowCompleted). Self-contained,
  zero wiring (P0-D will be the first producer). Durable Redis-Streams backend is a documented
  follow-up. 8 tests, ADR-0003.
- **Durable Task Runtime — schema + repository (`task_runtime`, P0-D D1)** — foundation for
  hours-long, crash-safe autonomous tasks. New additive tables `agent_jobs` (live state) +
  `agent_job_steps` (per-step checkpoints), created idempotently at startup; they sit **beside**
  `agent_task_executions` (which stays the final report — no breaking change). `JobRepository`
  provides atomic enqueue (+idempotency-key dedupe), `claim_next` via `FOR UPDATE SKIP LOCKED`
  (two workers never grab the same job), lease renew + expiry-based recovery (`find_expired`),
  step checkpoint/resume (`save_step`/`latest_done_step`), cooperative cancel/pause/resume, and
  listing. 8 tests against real Postgres. **Idle** in this slice — no worker yet, zero behaviour
  change; the inline `run_task` path is untouched (gated later by `TASK_RUNTIME` flag). ADR-0004.
- **Shared-state abstraction `platform_state` (P0-A, commit C1)** — one async `StateStore`
  contract with two behaviour-identical backends (`InProcessStateStore` now; `RedisStateStore`
  next). Prepares migrating in-process rate-limiter/circuit-breaker/working-memory/lock to a
  cross-worker store, unlocking horizontal scaling. Additive & fully reversible: default
  `STATE_BACKEND=inprocess` preserves current behaviour byte-for-byte; zero wiring into existing
  modules yet. `rate_incr` mirrors `security._check_rate_limit` semantics exactly. 12 contract
  tests. See `docs/adr/ADR-0001-shared-state.md`.
- **Shared-state Redis backend (P0-A, commit C2)** — `RedisStateStore` (cross-worker) with
  atomic Lua for `rate_incr` (sliding-window log, identical semantics to `_check_rate_limit`)
  and token-guarded `release_lock`; `SET NX PX` locks; native TTL. Opt-in via `STATE_BACKEND=redis`
  + `REDIS_URL`; startup wiring is **fail-open** (unreachable Redis → automatic fallback to
  in-process, boot never crashes). Same contract suite proven against Redis via `fakeredis`+`lupa`
  (10 parity tests) plus 3 wiring tests. Default remains `inprocess` (zero behaviour change).
  Dev-only test deps pinned in `requirements-dev.txt`.
- **Rate limiter on shared state (P0-A, commit C3)** — `bn_platform.security._check_rate_limit`
  now delegates to `StateStore.rate_incr` (behaviour-identical sliding-window; same 429 + headers).
  The function became `async`; all 24 call-sites across 12 modules (+ main.py public-demo indirection)
  were migrated to `await` (statically verified: zero un-awaited calls). With `STATE_BACKEND=redis`
  the management-endpoint rate limit becomes **cross-worker** (no longer bypassable by scaling out);
  default `inprocess` preserves current behaviour exactly. Parity tests for both backends. No public
  API/behaviour change; internal signature only.
- **Circuit breaker on shared state (P0-A, commit C4)** — the LLM provider circuit breaker
  (`ai_providers/router.py`) is now **hybrid**: a local in-process fast-path (so `is_open` stays
  ~0.5µs on the hot path) plus a `StateStore`-mirrored open-state (`cb:{provider}`), so a provider
  tripped on one worker is seen by others within ~1s (cross-worker reads are throttled to 1/s/provider
  to avoid per-call Redis latency). `is_open/ok/fail` became `async` (25 awaited call-sites in the
  router; statically verified); `state()` stays sync (used by `status()`, no I/O). Default `inprocess`
  preserves current behaviour. 5 unit + cross-worker tests.
- **Working-memory STM on shared state (P0-A, commit C5) — completes P0-A** — the conversation
  short-term-memory buffer (`memory_agent.MemoryStore`) now lives in `StateStore`
  (`mem:stm:{conv}`, trimmed to 60 turns + 1h TTL) instead of an unbounded in-process `_short`
  dict (fixes a latent per-process memory leak). `add_to_stm`/`clear_stm` became `async`
  (+ new async `get_recent`); both call-sites awaited. Audit note: the STM was **write-only/
  vestigial** (never read back for reasoning — the source of truth is the `messages` table +
  conversation summaries), so there is no observable behaviour change; follow-up recorded to
  either wire `get_recent()` into retrieval or remove STM. 6 tests. **P0-A (shared state) is now
  complete**: rate-limiter, circuit-breaker, and working-memory are all behind `StateStore`
  (opt-in cross-worker via `STATE_BACKEND=redis`; default in-process unchanged).

### Added — Billing & Pricing
- **Buyer tax identity (NPWP)** on invoices for Indonesian faktur pajak; snapshotted per invoice.
- **Enterprise SSO via OpenID Connect (OIDC)** — per-org IdP config (Okta/Azure AD/Google Workspace/Auth0), authorization-code flow, JIT provisioning, encrypted client secret at rest. Optional (password login preserved).
- **Capacity add-ons** — purchase extra agents/team members/channels/knowledge docs beyond plan limits.
- **Price grandfathering** — existing subscribers keep their locked-in price when list prices rise.
- **PPN 11% tax breakdown** on invoices (tax-inclusive) and successful-login audit trail.
- **Prepaid overage** — top-up credits extend usage beyond plan quota; monotonic plan pricing curve; per-plan model gating with per-call token/input caps; enterprise floor price + quote flow.

### Added — Agents & Platform
- **Multi-agent orchestrator** engine (authenticated + RBAC) with dynamic routing, parallel execution, timeouts, and structured aggregation.
- **Agent Marketplace** publisher layer — author/publish agent templates, paid templates with revenue-share ledger, atomic install/uninstall with full sync.
- **MCP integration** — client (JSON-RPC over Streamable HTTP), registry, and tool-executor routing exposing discovered MCP tools to agents.
- **SSE streaming chat** endpoint (`POST /chat/{bot_id}/stream`).
- **Casper on-chain proof** anchoring for auditable AI decisions.

### Added — Infrastructure
- **Database HA** — opt-in advisory-lock leader election with heartbeat-based failover; opt-in connection-pool command timeout.

### Changed
- `main.py` decomposed via the strangler pattern into focused routers under `bn_platform/`.

### Fixed
- Marketplace uninstall now fully removes the agent (atomic delete + frontend refresh, no stale/orphan records).

### Housekeeping
- Repository audit: archived zero-reference developer/throwaway scripts under `archive/`, hardened `.gitignore` (test/tooling caches, editor/OS files), and added `CHANGELOG.md` / `PROJECT_STRUCTURE.md`.

---

> For the full, commit-level history see `git log`. This changelog summarizes
> user-facing and architectural changes.
