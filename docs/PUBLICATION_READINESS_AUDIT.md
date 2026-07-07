# Publication Readiness Audit

Perspective: buildathon judge, open-source developer, investor/user, security
reviewer, and a first-time visitor. Assessed on the `publish/global-final-polish`
branch (which includes the security hardening + submission docs).

## Skor Saat Ini (1–10)

| Area | Score | Notes |
|------|:---:|-------|
| README | 8 | Strong top hook (one-liner + verifiable Casper proof), full sections, links to docs. |
| Demo clarity | 6 | Tester playbook + winner demo script exist; **video still missing**. |
| Casper proof | 8 | Real contract package + 2 confirmed testnet deploys, verifiable on cspr.live. |
| Security readiness | 9 | White-box audit, Critical/High fixed, STRICT_SECRETS live, CodeQL/Dependabot, no secrets tracked. |
| Repo professionalism | 8 | Clean tree (no junk/secrets tracked), community standards, templates, sensible `.gitignore`. |
| Documentation | 9 | Architecture, positioning, security story, playbooks, proofs, checklists. |
| Test readiness | 8 | ~1126 tests; pure/unit subset runs in CI; security suites green. |
| CI/CD | 7 | CI + CodeQL + Dependabot added; active after merge. |
| UI/UX polish | 7 | Clean dashboard + Casper detail modal; no debug/TODO/leaky copy; screenshots not embedded in README. |
| Buildathon fit | 8 | Meets repo + application requirements; metadata + BUIDL still manual. |
| Global winner potential | 8 | Strong tech + real proofs; ceiling is demo video + story visibility. |

**Overall ≈ 7.8/10.** Engineering and docs are strong; remaining gaps are
presentation (video, GitHub metadata, BUIDL page, embedded screenshots).

## 20 Masalah Terbesar (prioritas turun)

1. No demo video (highest-impact missing item).
2. GitHub description empty.
3. GitHub topics empty.
4. GitHub homepage/website empty.
5. BUIDL/DoraHacks page not yet populated (copy is ready).
6. README has no embedded screenshots/GIF of the Casper proof card.
7. Casper "why it matters" could be even more front-and-center for skimmers.
8. `.env.example` was missing `DATABASE_URL`/`DEEPSEEK_API_KEY` placeholders (fixed here).
9. CodeQL/Dependabot not yet green (activate on merge).
10. No High/Critical confirmed clear until Security tab is checked post-merge.
11. Demo reproducibility depends on a live URL a judge can reach (confirm uptime).
12. Repo name `ai-bisnis` is less memorable than `botnesia` (optional rename).
13. Some docs are Indonesian, some English — intentional but note the split for judges.
14. Roadmap is present but spread across docs; ensure README links it clearly.
15. Contract source (Rust) build steps optional — clarify it's not required to test.
16. Mobile app build/run not demoed (web is the primary demo).
17. Screenshots exist under `docs/marketing/` but aren't surfaced in README.
18. No single "Start here for judges" pointer at the very top of docs.
19. Sample transactions are 2 — more recent confirmed deploys would strengthen it.
20. License is "All Rights Reserved" — fine for a hackathon, but note it limits reuse.

## Fix Plan

### Fixed langsung sekarang (safe, done in this branch)
- Added `DATABASE_URL`, `DEEPSEEK_API_KEY`, and other AI-key placeholders to `.env.example`.
- Verified repo is clean of tracked junk/secrets; `.gitignore` hardened for `.env*`, cache, vendor, data, logs, keys.
- Confirmed all security guards intact (secret guard, RBAC, billing, rate-limit, local-agent guard) and security suites green.
- Fixed 2 env-coupled tests to assert the code default (env-independent).
- Verified frontend has no debug logs, TODO/lorem, or stack-trace/secret leakage in UI copy.
- Submission docs present: positioning, architecture, security story, playbooks, proofs, checklists, BUIDL copy.

### Manual required (needs your data / GitHub / DoraHacks)
- Set GitHub description, homepage, topics (commands in `GLOBAL_FINAL_SUBMISSION_CHECKLIST.md`).
- Record and link the demo video (`WINNER_DEMO_PLAYBOOK.md`).
- Populate the BUIDL page (`BUIDL_PAGE_COPY.md`).
- Embed 2 screenshots in README (assets exist under `docs/marketing/screenshots/`).
- After merge: enable Dependabot alerts; confirm no High/Critical in the Security tab.

### Jangan disentuh sekarang (berisiko)
- No production deploy, migration, or `.env` edits.
- No large dependency upgrades (cryptography/pydantic-settings/pypdf) without a
  tested Dependabot PR.
- No repo rename or license change without your decision.
- No layout/feature changes to the live app.
