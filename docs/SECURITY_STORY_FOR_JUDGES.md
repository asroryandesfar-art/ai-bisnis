# Security Story (for judges)

BotNesia is a **security-hardened MVP**. A structured white-box audit was
performed and the Critical/High findings were remediated, tested, and deployed.
We do **not** claim "100% secure" — we claim documented defensive controls and a
production hardening checklist. Everything below is verifiable in the repo.

## What was done
- **White-box security audit** across auth, RBAC, multi-tenant isolation,
  billing, API, AI-agent, secrets, dependencies, and deployment.
  Evidence: `docs/SECURITY_AUDIT_BOTNESIA.md`.
- **Remediation log** with one commit per fix and test results.
  Evidence: `docs/SECURITY_FIX_LOG.md`.

## Critical / High issues fixed (with defensive controls)
| ID | Issue | Control implemented |
|----|-------|---------------------|
| C-01 | Weak/default `SECRET_KEY` | Startup guard (`audit_secret_key`); `STRICT_SECRETS=1` fail-closed; separate `INTEGRATION_ENCRYPTION_KEY`. |
| H-01 | RBAC privilege escalation | Server-side role ceiling — only owner grants owner/admin; no self-promotion. |
| H-02 | Billing/plan bypass | `PATCH /org/plan` cannot upgrade for free; upgrades require verified payment webhook. |
| H-03 | AI/chat cost abuse | Rate limit keyed on server-derived IP (anti-spoof), not client-supplied id. |
| H-04 | Local agent command risk | Hard denylist, secret-file guard, working-dir restriction, audit log. |

## Additional hardening (Medium/Low)
- Generic error responses (no stack/DB leakage), signed media URLs
  (`MEDIA_REQUIRE_SIGNATURE`), CORS restricted to app origins (widget stays
  open), security headers (HSTS/X-Frame-Options/nosniff/Referrer-Policy),
  Swagger `/docs` disabled in production, patched dependencies
  (`python-jose>=3.5`, `python-multipart>=0.0.31`), login timing equalized to
  prevent user enumeration, and a prepared Postgres RLS migration.

## AI-specific defensive controls
- **Prompt-injection guard** blocks "ignore previous instructions / show system
  prompt / read .env / show API key" before any model call.
- **Output redaction** removes secret-like patterns and system-prompt leakage
  from AI responses.
- **Tenant isolation** on every knowledge/RAG query (`org_id`); the DB tool uses
  a server-side allowlist.
- **Backend-authoritative plan gating** — clients cannot force the PRO model.

## Secrets posture
- No secrets in the repo: `.env*` (except `.env.example`) is git-ignored; a
  secret scan of the diff is clean. API keys, `SECRET_KEY`, wallet/private keys,
  tokens, and passwords are never committed.
- Casper wallet/signing keys and the AI API key are provided via
  environment/secret manager only.

## Test evidence
- Security-focused test suites pass (secret guard, RBAC escalation, billing,
  rate-limit, local-agent command guard, CORS, headers, media signing, login
  enumeration). See `docs/SECURITY_FIX_LOG.md` for counts and commit hashes.
- CodeQL (Python + JS/TS) and Dependabot (pip/npm/actions) run on the repo.

## Production hardening checklist (live status)
- [x] Strong `SECRET_KEY` + `STRICT_SECRETS=1`
- [x] `CHANNEL_ENCRYPTION_KEY` valid (urlsafe-base64, 32 bytes)
- [x] `ENABLE_API_DOCS=0` (Swagger not exposed)
- [x] Security headers active
- [x] CORS restricted to app origins
- [x] No secrets committed
- [ ] `MEDIA_REQUIRE_SIGNATURE=1` (mechanism ready; enable when convenient)
- [ ] RLS migration applied (prepared; needs maintenance window)

> Language we use: **"security-hardened MVP", "defensive controls implemented",
> "production hardening checklist documented"** — not "100% secure".
