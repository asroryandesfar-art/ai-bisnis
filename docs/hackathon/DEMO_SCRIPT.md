# BotNesia — 3-Minute Demo Script (Casper Agentic Buildathon 2026)

Every step below has been **live-verified** against the running instance
before this script was written — no step relies on a feature that hasn't
actually been clicked and confirmed working end-to-end (including the Local
Agent round-trip: real file written, `pytest` run, on-chain anchor).

**The one-sentence pitch:** *Businesses increasingly let AI make real
decisions — and now write real code — but those actions live in editable
logs, unauditable and disputable. BotNesia makes autonomous AI
**accountable by design**: every important decision and every code change is
anchored on **Casper** as an immutable, independently verifiable proof.*

**Setup:** `https://botnesia.uk` open and logged in to `/dashboard`. Pick one
marketplace demo bot for the chat widget. Have the `botnesia-agent`
(Local Agent) running on your laptop and connected. Have a `cspr.live`
testnet tab ready.

**Honesty note (say it if asked):** this is a click-through of **real
production features on the founder's own live tenant** — not a seeded fake
workspace. The only explicitly simulated part is Investor Demo Mode's
declining-revenue *scenario* (it says so on screen); the AI, the code
execution, and the Casper anchoring are all real.

---

### 0:00–0:20 — Hook (landing page)

> "AI now makes business decisions and writes code on its own. But logs can
> be edited — so who's accountable? BotNesia is an AI Workforce that
> **proves** what it did: every decision and code change is anchored on
> Casper, immutable and verifiable by anyone."

Show the landing page. One line, then move — the proof is in the clicks.

---

### 0:20–1:00 — Streaming multi-agent chat + anchor a decision on Casper

Open the chat widget. Send: **"Haruskah kami menaikkan harga paket Pro?"**

- The answer **streams in token-by-token in ~2 seconds** — call out: *"Real
  DeepSeek inference, streaming live — first token in about two seconds, not
  a spinner."*
- Send a simple one next (**"Jam buka toko?"**) — instant. *"A real intent
  router picks the fast path for simple questions and the deep multi-agent
  pipeline for complex ones."*

Now go to **Command Center → Casper Agentic Workflow**, click **One-Click
Demo** (or type a real decision). When it resolves:

> "That business decision was just analyzed by our real DeepSeek Brain — and
> its hash was anchored to Casper Testnet."

Click **View Deploy ↗** → the **real `cspr.live` deploy page** opens.
*"Anyone can verify this AI decision was made, exactly as recorded, at this
time. It can never be altered after the fact."*
(The anchored payload is a genuine AI decision — `ai_generated: true`, real
model, real reasoning — not a template.)

---

### 1:00–2:15 — The flagship: **Casper Engineer** (autonomous AI software engineer)

Navigate to **Agent OS → Casper Engineer**. This is the part nobody else has.

1. Type a real goal: **"Tambah fungsi `multiply(a,b)` di repo, dengan unit
   test, dan pastikan test lulus."** Run it.
   → Watch the structured artifact appear: **Planning → Repository Analysis →
   Self-Verification → Self-Critique** (with severity-colored issues and an
   improved plan). *"It plans and critiques its own work before writing a
   line — Senior Engineer + Tech Lead + QA in one."*

2. Click **Investigasi otonom (read-only)**. → The trace shows the agent
   **choosing its own reads** on your machine via the Local Agent
   (`tree` → `read_file main.py` → …) and summarizing what it found.
   *"That's a real agentic loop reading the actual repo on my laptop — read-only,
   nothing written yet."*

3. Click **Usulkan langkah eksekusi** → an ordered plan of concrete tool
   calls (`read_file` → `write_file` → `run_command pytest`), writes flagged
   **"perlu approval"**. Click **Jalankan di mesin saya** on the write step →
   approve the prompt on your laptop → **the file is actually written to
   disk**. Run the `pytest` step → **green**. *"It just wrote production code
   and proved the tests pass — on my machine, with me approving each write."*

4. Click **Anchor ke Casper** on the run → a **verified-on-chain badge** +
   deploy hash appears. Click through to `cspr.live`. *"And the whole
   engineering artifact — what it decided, wrote, and verified — is now an
   immutable Casper proof."*

> "An AI that writes real code **and** proves what it did, immutably, on
> Casper. That's the loop."

---

### 2:15–2:40 — Safety is real, not a mockup

Still in Casper Engineer / Local Agent, show the guardrails:
- Try a destructive command (`rm -rf`) → **blocked by the device policy**
  even though I approved it. Try reading `.env` → **blocked** (secret guard).
- *"Autonomous, but never unsupervised: a server-side allowlist, a device-side
  destructive/secret denylist, and per-write human approval. Three layers,
  enforced in code — not a UI suggestion."*

---

### 2:40–3:00 — Close

> "Multi-agent AI that acts — answers customers, makes business decisions,
> writes and tests code — and **proves every important action on Casper** so
> it can never be disputed. Multi-tenant SaaS underneath, **1592 automated
> tests, zero failing**, live today at botnesia.uk. BotNesia isn't a chatbot.
> It's accountable autonomous AI, on Casper."

---

## Extended cut (4–5 minutes)

- **Investor Demo Mode** (`#investor-demo`): one-click, a real LLM diagnoses a
  simulated declining-revenue company — root cause, prioritized action plan,
  predicted recovery. (Scenario is simulated; the analysis is a real model call.)
- **Billing → real Midtrans Production** (`#billing`): top-up → real Midtrans
  Snap page → live invoice status from the server-to-server webhook only.
- **Observability** (`#observability`): after a complex chat, show the real
  `agent_executions` — reasoning / planner / devil's-advocate / verification /
  synthesis — proof the multi-agent pipeline actually ran (not UI theater).

---

## Backup talking points

- **"Is this mocked?"** — No. **1592 automated backend tests, 0 failing.**
  Real DeepSeek inference on every step; the Casper anchor opens a real
  `cspr.live` deploy; the Casper Engineer file-write and `pytest` run happen
  on the presenter's actual laptop via the Local Agent.
- **"Is the Casper part just a hash on a chain?"** — The anchored payload is a
  genuine AI decision / engineering artifact (real model, real reasoning,
  `ai_generated: true`), not a template. Real mode calls the deployed AI Proof
  Registry contract on Casper Testnet; demo mode (no keys) is honestly labeled.
- **"What stops the coding agent going rogue?"** — Three enforced layers:
  server-side tool allowlist, device-side destructive/secret denylist
  (`botnesia_local_agent.py`), and per-write human approval on the machine.
  Nothing auto-runs.
- **"How is this multi-tenant?"** — Every table scoped by `org_id`; 5-tier
  RBAC; see `docs/SECURITY.md` and `docs/DATABASE.md`.
