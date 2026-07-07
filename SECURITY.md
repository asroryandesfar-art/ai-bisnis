# Security Policy

BotNesia is a multi-tenant SaaS AI platform with a Casper Testnet anchoring
layer. We take security seriously and welcome responsible disclosure.

## Reporting a vulnerability

Please **do not** open a public GitHub issue for security problems.

- Email: **asroryandesfar@gmail.com** with subject `SECURITY: <short summary>`.
- Include: affected component, steps to reproduce, impact, and (if possible) a
  proof-of-concept. Please avoid destructive testing against production.
- We aim to acknowledge within **72 hours** and provide a remediation timeline
  after triage.

Please give us reasonable time to fix an issue before public disclosure.

## Scope

In scope:
- Backend API (`main.py`, `bn_platform/`, `ai_providers/`, `deepseek_brain.py`).
- Auth, RBAC, multi-tenant isolation, billing, rate limiting.
- Casper anchoring (`casper/`, `casper_anchor.py`).
- Web dashboard (`frontend/`) and mobile app (`mobile/`).

Out of scope:
- Vendored third-party code under `vendor/` and `.tts_vendor/`.
- Social engineering, physical attacks, and DoS/volumetric testing.
- Findings that require a compromised admin/owner account.

## Secrets policy

- **No secrets are committed.** `.env*` (except `.env.example`) is git-ignored;
  API keys, `SECRET_KEY`, wallet/private keys, tokens, and passwords must never
  be committed. `.env.example` contains placeholders only.
- `SECRET_KEY` must be a strong random value (>= 32 chars). A startup guard
  (`audit_secret_key` / `validate_startup_secrets`) rejects weak/default values;
  set `STRICT_SECRETS=1` in production to fail-closed.
- Integration credentials are encrypted with `INTEGRATION_ENCRYPTION_KEY`
  (falls back to `SECRET_KEY`); channel credentials with `CHANNEL_ENCRYPTION_KEY`
  (urlsafe-base64, 32 bytes). Casper wallet keys are provided via env/secret
  manager only — never in the repo.
- The DeepSeek/AI API key is server-only; it is never sent to the frontend, and
  the model router (`deepseek_brain.py`) redacts secret-like patterns from AI
  output before returning it.

## Dependency policy

- **Dependabot** is enabled (`.github/dependabot.yml`) for pip, npm, and GitHub
  Actions.
- **CodeQL** scans Python and JavaScript/TypeScript on every push/PR and weekly.
- Pinned dependencies are patched for known CVEs (e.g. `python-jose>=3.5`,
  `python-multipart>=0.0.18`). Run `pip-audit -r requirements.txt` and
  `npm --prefix mobile audit` before releases.
- We do not perform large, breaking dependency upgrades without test coverage.

## Production hardening checklist

- [ ] `SECRET_KEY` strong (>= 32 chars) and `STRICT_SECRETS=1`.
- [ ] `INTEGRATION_ENCRYPTION_KEY` set (old key on rotation) or channels reconnected.
- [ ] `CHANNEL_ENCRYPTION_KEY` valid (urlsafe-base64, 32 bytes).
- [ ] `MEDIA_REQUIRE_SIGNATURE=1` (signed media URLs enforced).
- [ ] `ENABLE_API_DOCS=0` (Swagger/OpenAPI not exposed publicly).
- [ ] `METRICS_AUTH_TOKEN` set (protects `/metrics` before public exposure).
- [ ] `CORS_ALLOWED_ORIGINS` restricted to real dashboard origins.
- [ ] Security headers active (CSP/HSTS/X-Frame-Options via middleware).
- [ ] Backend enforces plan/role/tenant on every request (no client-trusted auth).
- [ ] Row-Level Security migration reviewed (`migrations/README_RLS_ROLLOUT.md`).
- [ ] No High/Critical security alerts open in GitHub Security tab.

See `docs/SECURITY_AUDIT_BOTNESIA.md` and `docs/SECURITY_FIX_LOG.md` for the
most recent white-box audit and remediation log.
