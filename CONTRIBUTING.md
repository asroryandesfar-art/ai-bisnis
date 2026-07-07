# Contributing to BotNesia

Thanks for your interest. This guide covers local setup, branching, and the
rules for opening a pull request.

## Local setup

Prerequisites: Python 3.12, PostgreSQL 16, Node 20 (for the mobile app).

```bash
# 1. Clone
git clone https://github.com/asroryandesfar-art/ai-bisnis.git
cd ai-bisnis

# 2. Python deps
pip install -r requirements.txt

# 3. Config — copy the example and fill in your own values (never commit .env)
cp .env.example .env
#   Set at least: DATABASE_URL, SECRET_KEY (>=32 random chars),
#   and one AI provider key (GEMINI_API_KEY / DEEPSEEK_API_KEY / ...).

# 4. Run (DB schema migrates automatically on first request)
python -m uvicorn main:app --host 127.0.0.1 --port 8000
# Dashboard: http://localhost:8000/dashboard   Casper demo: http://localhost:8000/casper
```

Mobile app:

```bash
cd mobile
npm ci
npm start   # Expo
```

## Running tests

```bash
# Pure/unit tests (no DB, no secrets) — these run in CI:
python -m pytest test_deepseek_brain.py test_rbac_privilege_escalation.py -q

# Full suite (needs a live DB + AI keys):
python -m pytest -q
```

The full suite has a small number of tests that require live AI providers;
those are expected to fail without keys and are not run in CI.

## Branching

- `main` is the deployable branch. Do not commit directly to `main`.
- Create a topic branch: `feature/<name>`, `fix/<name>`, `security/<name>`,
  `chore/<name>`, or `docs/<name>`.
- Keep one logical change per branch; prefer small, reviewable PRs.

## Pull request rules

1. **Run tests before opening a PR** and make sure the CI-relevant tests pass.
2. Describe *what* changed and *why*. Link related issues.
3. Add/update tests for behavior changes.
4. Update docs (README, `docs/`) when relevant.
5. Keep unrelated refactors out of the PR.
6. At least one review before merge; do not force-push shared branches.

## Never commit secrets

- Do not commit `.env`, API keys, `SECRET_KEY`, wallet/private keys, tokens, or
  passwords. `.env*` (except `.env.example`) is git-ignored.
- If you accidentally commit a secret: rotate it immediately and tell a
  maintainer — do not just delete the file (git history keeps it).
- CodeQL + Dependabot run on every PR; address High/Critical findings before merge.

## Code style

Match the surrounding code (naming, comment density, idioms). This project does
not use `from __future__ import annotations` in modules where FastAPI resolves
`Depends(...)` type hints at runtime.
