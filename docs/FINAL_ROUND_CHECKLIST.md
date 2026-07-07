# Casper Agentic Buildathon — Final Round Checklist

Status legend: ✅ Done · 🟡 Partial · 🖐 Manual required (you must do it on
GitHub/DoraHacks) · ❌ Missing

_Last updated by the repo audit. Items marked 🖐 cannot be done from the codebase._

## GitHub Repository

| Requirement | Status | Notes |
|-------------|--------|-------|
| Repository public, proper name | ✅ | `asroryandesfar-art/ai-bisnis` is public. (Name could be renamed to `botnesia` — optional, 🖐.) |
| Description | 🖐 | Currently empty — run `gh repo edit --description "..."` (command below). |
| Website / homepage | 🖐 | Currently empty — run `gh repo edit --homepage "..."`. |
| Topics (casper-blockchain, casper-network, buildathon, …) | 🖐 | Currently none — run the `--add-topic` command below. |
| README.md complete & comprehensive | ✅ | 314+ lines: overview, architecture, features, stack, run, tests, Casper, security, submission. |
| GitHub community standards | ✅ | Added: `LICENSE`, `SECURITY.md`, `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md`, issue-ready README. |
| CodeQL active | 🟡 | Workflow added (`.github/workflows/codeql.yml`); becomes active after merge to `main` + first run. |
| Dependabot alerts/config | 🟡 | Config added (`.github/dependabot.yml`); enable Dependabot **alerts** in repo Settings → Security (🖐). |
| CI / security tools active | 🟡 | CI added (`.github/workflows/ci.yml`); active after merge. |
| No open High/Critical security alerts | 🖐 | Verify in GitHub → Security tab after CodeQL/Dependabot run. Local audit: no High/Critical found (see below). |

## Application

| Requirement | Status | Notes |
|-------------|--------|-------|
| MVP fully functional & deployed on Casper Testnet | ✅ | Live app; real confirmed anchoring deploys on casper-test. |
| Intuitive UI workflow | ✅ | Dashboard SPA; `/casper` tab shows Action · AI Decision · Casper Status · Tx Hash · Timestamp. |
| Demo video OR playbook with step-by-step testing | 🟡 | Playbook added (`docs/CASPER_FINAL_SUBMISSION_PLAYBOOK.md`). Demo **video link** still 🖐. |
| Instructions concrete, not marketing | ✅ | Playbook is operational/tester-focused. |
| Contract package hash(es) | ✅ | Real: `897c4bd6…a9f0` (see `docs/CASPER_TESTNET_PROOFS.md`). |
| Sample Casper Testnet transactions | ✅ | Two real confirmed deploys documented with explorer links. |
| Hashes/transactions described & BUIDL-ready | ✅ | Copy-paste block in `docs/CASPER_TESTNET_PROOFS.md`. Paste into BUIDL page (🖐). |

## Still requires you (manual)

1. GitHub **description** — `gh repo edit` command below.
2. GitHub **website/homepage** — set to the live demo URL.
3. GitHub **topics** — add the buildathon topics.
4. **Demo video link** — record and add to README + BUIDL page.
5. **DoraHacks / BUIDL page** — paste contract + transaction proofs.
6. Enable **Dependabot alerts** and confirm **no High/Critical** in Security tab.

## Manual commands (run after reviewing)

```bash
# Description
gh repo edit asroryandesfar-art/ai-bisnis \
  --description "BotNesia — enterprise multi-agent AI platform that anchors AI business decisions on Casper Testnet as immutable, verifiable proofs. Casper Agentic Buildathon 2026."

# Homepage (replace with the exact live demo URL)
gh repo edit asroryandesfar-art/ai-bisnis --homepage "https://botnesia.uk"

# Topics
gh repo edit asroryandesfar-art/ai-bisnis \
  --add-topic casper-blockchain \
  --add-topic casper-network \
  --add-topic buildathon \
  --add-topic ai-agents \
  --add-topic multi-agent \
  --add-topic fastapi \
  --add-topic blockchain \
  --add-topic saas
```

Enable Dependabot alerts (UI): repo → **Settings → Code security and analysis**
→ enable *Dependabot alerts* and *Dependabot security updates*.
