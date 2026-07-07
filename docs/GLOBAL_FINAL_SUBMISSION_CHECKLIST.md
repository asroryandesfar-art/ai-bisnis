# Global Final Submission Checklist

Status: ✅ Done · 🟡 Partial (active after merge) · 🖐 Manual required · ❌ Missing

| Area | Status | Evidence | Manual action |
|------|--------|----------|---------------|
| Repo public | ✅ | `gh repo view` → `isPrivate:false` | — |
| Repo name proper | 🟡 | `asroryandesfar-art/ai-bisnis` | Optional: rename to `botnesia` |
| Description | 🖐 | empty | `gh repo edit --description "…"` |
| Website / homepage | 🖐 | empty | `gh repo edit --homepage "…"` |
| Topics | 🖐 | none | `gh repo edit --add-topic …` |
| README | ✅ | `README.md` (one-liner, problem, Casper, security, roadmap) | — |
| License | ✅ | `LICENSE` | — |
| Security policy | ✅ | `SECURITY.md` | — |
| Contributing / Code of Conduct | ✅ | `CONTRIBUTING.md`, `CODE_OF_CONDUCT.md` | — |
| CodeQL | 🟡 | `.github/workflows/codeql.yml` | Confirm green after merge |
| Dependabot | 🟡 | `.github/dependabot.yml` | Enable Dependabot alerts in Settings |
| CI | 🟡 | `.github/workflows/ci.yml` | Confirm green after merge |
| Issue/PR templates | ✅ | `.github/ISSUE_TEMPLATE/`, `PULL_REQUEST_TEMPLATE.md` | — |
| No High/Critical alerts | 🟡 | npm audit: 0 high/critical; pip pins patched | Verify Security tab post-merge |
| MVP deployed | ✅ | live app; 2 confirmed Casper txs | — |
| Demo video | 🖐 | playbook ready (`WINNER_DEMO_PLAYBOOK.md`) | Record + add link |
| DoraHacks playbook | ✅ | `CASPER_FINAL_SUBMISSION_PLAYBOOK.md` | — |
| Casper Testnet contract hash | ✅ | `897c4bd6…a9f0` in `CASPER_TESTNET_PROOFS.md` | — |
| Sample transaction | ✅ | 2 confirmed deploys documented | — |
| BUIDL page completed | 🖐 | copy ready (`BUIDL_PAGE_COPY.md`) | Paste into DoraHacks |
| Security fix active | ✅ | `SECURITY_FIX_LOG.md`; STRICT_SECRETS live | — |
| Final smoke test passed | ✅ | live: /health 200, /docs 404, chat routes via 3-brain | — |

## Manual commands
```bash
gh repo edit asroryandesfar-art/ai-bisnis \
  --description "BotNesia — enterprise multi-agent AI platform that anchors AI business decisions on Casper Testnet as immutable, verifiable proofs. Casper Agentic Buildathon 2026." \
  --homepage "https://botnesia.uk" \
  --add-topic casper-blockchain --add-topic casper-network --add-topic buildathon \
  --add-topic ai-agents --add-topic multi-agent --add-topic fastapi \
  --add-topic blockchain --add-topic saas
```
Then: repo → Settings → Code security and analysis → enable Dependabot alerts +
security updates.
