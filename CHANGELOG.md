# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/); the project follows a
trunk-based, continuously-deployed workflow (no fixed release cadence yet), so
entries are grouped by theme rather than semantic version tags.

## [Unreleased]

### Added — Efficiency & Operability (Fase 3)
- **Cost Router (P2-A)** — model selection by task class, not just a binary economy/quality split.
  New `cost_intelligence.classify_task_class` (simple/medium/complex/coding/vision, deterministic) +
  `router_params` mapping to `{tier, task_type}` the `SmartModelRouter` already understands, plus
  `SmartModelRouter.route_for_message/stream_for_message` (classify → route). Wired into
  `chat_streaming.stream_answer` (opt-in `user_message`/`org_id`), gated per-org by
  `is_enabled("cost_router")` — off / no message → the previous `task_type="standard"` behaviour
  byte-for-byte. Routes light chat to the cheap brain (DeepSeek-chat), complex→reasoning (R1),
  coding→coding-model, vision→Gemini — cutting spend while improving fit; the Evaluation scores
  (P1-D) can later calibrate the mapping. GOTCHA baked in: simple/medium use `task_type="standard"`
  (not `"chat"`, which is in `deepseek._SKIP_TASKS`). 8 tests. ADR-0009.

### Added — Cognitive Core (Fase 2)
- **Policy engine (`policy_engine`, P1-C)** — a single declarative governance point for agent actions:
  `PolicyEngine(rules)` → `Decision(allow|block|approval|mask)`. `check_tool` (dangerous tools →
  approval), `check_url` (blacklisted domains → block, incl. subdomains), `check_cost` (cost > limit →
  approval), and `mask` (redact PII: email/phone/long-number → placeholders). Pure/no-I/O and testable;
  reuses the existing approval workflow (returns APPROVAL rather than executing it). First enforcement
  hook: the durable runner now **masks PII before storing episodic long-term memory** (so raw emails/
  phones aren't retained in the vector store), gated per-org by `is_enabled("policy_engine")`. 9 tests
  (8 engine + 1 runner PII-mask integration). ADR-0008.
- **Evaluation framework (`evaluation`, P1-D)** — automatic post-task quality scoring, stored in a new
  additive `task_evaluations` table. `Evaluator.evaluate` computes deterministic metrics (tool_success,
  answered, verified, confidence) plus optional LLM-judge dimensions (accuracy, hallucination-free,
  reasoning_quality, citation) via an injected `judge_agent` (fail-open), and a weighted `overall`.
  Integrated into `DurableJobRunner` (`evaluator=…`): every finished job (linear **and** cognitive)
  is scored and persisted automatically, gated per-org by `is_enabled("evaluation")`, best-effort
  (an eval failure never fails the job). Gives an objective quality signal for A/B, regression
  detection, and future Cost-Router calibration. 6 tests (metrics/empty/judge/fail-open/store +
  auto-eval-on-completion). ADR-0007.
- **Long-term semantic memory (`long_term_memory`, P1-B.1)** — closes the audit's "memory is
  write-only / never retrieved during reasoning" gap. New additive `agent_memories` table with a
  **pgvector** `vector(384)` column (real pgvector, verified available); `SemanticMemory.store/
  retrieve/summarize` embed content/query and fetch the top-k by cosine similarity
  (`embedding <=> query`). Embeddings use an injectable `embed_fn` (default lazy
  `kb_embeddings.generate_local_embedding` — local, free, no API; tests inject a deterministic fake).
  Scopes: semantic/episodic/task/reasoning + a `subject` partition (user/conversation/agent). Honest
  graceful degrade: no embedding → stored without a vector and retrieval falls back to recency; no
  pgvector → schema is skipped and the store no-ops safely. 5 tests against real Postgres+pgvector.
  Self-contained, zero consumers yet (retrieval wiring into reasoning is P1-B.3, flag-gated). ADR-0006.
- **Long-term memory wired into reasoning (P1-B.3)** — durable **cognitive** jobs now *retrieve*
  relevant memories before reasoning (`memory.summarize(query=goal, subject=agent)` → injected into
  the reasoning context) and *store* the outcome afterwards (as an `episodic` memory weighted by the
  Critic score) — so the agent actually recalls and learns across sessions. Gated per-org by
  `is_enabled("long_term_memory")` (OFF → no recall/store). `DurableJobRunner(memory=…)` is injectable
  for tests. 1 integration test proving recall-injects-context + experience-is-stored. (Wiring into
  the chat `enrich_context` path remains as a follow-up.)
- **Cognitive loop (`cognitive_loop`, P1-A) — Planner→Worker→Critic**  — closes the audit's #1
  gap (single-pass execution / at most one revision). `CognitiveLoop.run(agent, goal)` iterates
  Planner → Worker → Critic → (accept | revise | replan) until the Critic accepts (score ≥ threshold),
  the budget runs out (`max_iters`/`deadline_s`), or the LLM is unavailable (degraded → best-effort,
  never loops forever). Dependency-injected (agent only needs `_call_llm_json`), fail-open, with an
  optional `worker_fn` to swap the default LLM worker for a tool-using worker (`task_engine`). Self-
  contained, zero wiring — consumers adopt it behind `is_enabled("cognitive_loop")`; it is designed
  to run as a durable job (one checkpoint per iteration). 7 tests, ADR-0005.
- **Cognitive loop — tool worker + `BaseAgent.reason()` (P1-A.2)** — `make_tool_worker` lets the loop's
  Worker actually *act* via the agent tool-loop (`_call_llm_with_tools`), not just reason; and every
  agent gained an additive `reason(goal, use_tools=…)` convenience that runs the Planner→Worker→Critic
  loop (the existing `run_task`/`parse_intent` paths are unchanged). Fail-open. 4 more tests (11 total).
- **Cognitive loop — durable integration (P1-A.3)** — a durable job with `ctx.mode="cognitive"` now
  runs the Planner→Worker→Critic loop as a checkpointed `cognitive` step (resume reuses the saved step;
  final row still written to `agent_task_executions` with `verification={verified, score}`; emits
  TaskFinished/Failed). Usable through the **existing** `POST /api/jobs` API (just pass `ctx`). Gated
  per-org by `is_enabled("cognitive_loop")` — flag OFF falls through to the linear path (safe default).
  3 tests (completes, crash-resume reuses step, flag-off→linear). The inline `run_task` path is
  untouched.

### Added — Platform Foundation (Fase 1)
- **Cross-worker validation + staging runbook (P0)** — 5 tests drive TWO `RedisStateStore`
  instances over ONE shared fakeredis server (through the real Redis+Lua code path) proving
  rate-limit, distributed-lock, kv/hash/list, circuit-breaker, and working-memory STM are truly
  consistent across "workers" — the strongest validation possible without a live Redis server.
  `docs/RUNBOOK-staging-validation.md` gives the exact steps to validate with real Redis + Celery
  worker/beat (2-instance shared rate-limit, enqueue→worker→completed, kill-worker→resume, cancel/
  pause/DLQ-replay, fail-open) before a production canary.
- **Foundation validated against a REAL Redis server (`scripts/validate_redis_foundation.py`)** —
  runs an actual `redis-server` (via `redislite`, no sudo) and proves 9/9: production
  `build_redis_store` wiring, cross-connection shared rate-limit, `rate_incr` atomicity under 200
  concurrent requests (exactly N allowed), real server-side TTL expiry, distributed lock
  (NX/token/TTL), and cross-worker circuit-breaker + working-memory STM — the things fakeredis +
  a mocked clock cannot prove (real Lua, real concurrency, real TTL).
- **Multi-process shared-state proven locally (`scripts/validate_multiprocess_redis.sh`)** — spins up
  TWO real uvicorn instances with `STATE_BACKEND=redis` against one redislite server and shows the
  rate limit is shared **across separate processes**: 3 hits to :8000 + 3 hits to :8001 (same IP) →
  the 6th returns **429** (a per-process limiter would never 429 with only 3 per instance). Confirms
  the HTTP→`_check_rate_limit`→`StateStore`→Redis path works cross-process. Remaining real-infra gate
  is only a real Celery worker/beat + multi-host + load run (see the runbook).
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
- **Durable Task Runtime — runner (`task_runtime.DurableJobRunner`, P0-D D2/D3)** — executes a job
  as checkpointed steps (plan → subtask×N → verify → report), so it **resumes** from the last
  'done' step after a crash, supports **cooperative cancel/pause** at step boundaries, **retry/DLQ**
  (attempts vs max_attempts), and per-step timeout + progress. It reuses the agent primitives and
  `task_engine._persist_task_execution` so the final `agent_task_executions` row is identical to the
  inline path — **the inline `task_engine.run_task` is left untouched** (no regression risk). Emits
  TaskStarted/Finished/Failed on the event bus (best-effort). 4 tests against real Postgres
  (complete+persist, resume-skips-plan, cancel, retry→DLQ). No worker yet (D4); still idle/opt-in.
- **Durable Task Runtime — worker + HTTP API (`task_runtime.worker` + `bn_platform/jobs_router`,
  P0-D D4/D5)** — the runtime is now usable end-to-end. Worker: `run_one_job`/`drain_jobs` (Celery-free,
  testable) + `make_registry_agent_builder` (resolve agent by name → `build_agent`, kwargs auto-filtered)
  + Celery task `task_runtime.run_pending` with a 30s beat that drains the queue and recovers
  expired-lease jobs (cheap no-op when empty). API `POST /api/jobs` (enqueue, triggers the worker
  best-effort), `GET /api/jobs` + `/{id}` (status + steps), `POST /api/jobs/{id}/cancel|pause|resume`
  — RBAC `workforce.read/write`, rate-limited, mounted at `/api/jobs` (401 verified). 9 tests (4 worker
  + 5 API) against real Postgres. Default execution path (inline `run_task`) unchanged; the durable
  path is opt-in. Remaining (D6): SSE progress, DLQ replay, domain-router `async=true` integration
  behind `TASK_RUNTIME`/feature flag, kill-worker→resume chaos test in CI.
- **Durable Task Runtime — D6 (completes P0-D)** — SSE progress `GET /api/jobs/{id}/stream`
  (emits on status/progress change, ends at terminal state); DLQ replay `POST /api/jobs/{id}/retry`
  (+ `JobRepository.requeue_dlq`); and the four domain task endpoints (finance/hr/operations/marketing
  `POST /*/run-task`) gained an optional `?async=true` that routes to a durable job **only when the
  `durable_runtime` feature flag is enabled for the org** (default OFF → the inline path is
  byte-identical; supports per-org canary). Added a chaos test proving crash→recovery→resume
  (expired lease → reclaim → runner resumes from checkpoint without re-running completed steps).
  9 new tests. **P0-D (durable task runtime) is complete** end-to-end (schema→repo→runner→worker→
  API→SSE→DLQ→domain integration); real Redis/Celery-worker validation in staging is the next gate
  before production canary.
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
