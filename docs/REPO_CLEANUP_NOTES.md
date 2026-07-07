# Repo Cleanup Notes

Record of what was reviewed for publication cleanliness. Nothing was deleted;
the repo was already clean. This documents the checks so a reviewer can trust
the tree.

## Tracked-file review (result: clean)
- **No junk tracked:** 0 files matching `__pycache__`, `*.pyc`, `.pytest_cache`,
  `.DS_Store`, `*.log`, `*.tmp`, `*~`, `*.bak`, `*.save`.
- **No secrets tracked:** `.env` and all `.env*` backups are git-ignored
  (`.env.example` is the only tracked env file, placeholders only). Secret-pattern
  scan of tracked files is clean (only dummy fixtures in `test_deepseek_brain.py`
  used to test output redaction).
- **No vendored bloat tracked:** `vendor/`, `.tts_vendor/`, and `data/` are
  git-ignored (0 tracked files).
- **Working tree clean:** no untracked artifacts.

## Tracked binaries (kept — all legitimate)
| File | Why it stays |
|------|--------------|
| `ai_proof_registry.wasm` | Compiled Casper smart contract (part of the submission). |
| `docs/marketing/BotNesia-Company-Profile.pdf` | Submission/marketing asset. |
| `docs/marketing/screenshots/*.png` | Product screenshots (can be embedded in README). |
| `frontend/public/assets/brand/*.png` | Brand logos/favicons used by the app. |
| `mobile/assets/*.png` | Mobile app icons/splash. |

## `.gitignore` coverage (verified)
Ignored: `.env*` (except `.env.example`), `__pycache__/`, `*.py[cod]`, `_tmp/`,
`vendor/`, `data/`, `*.db/*.sqlite*`, `*.log`, `*.pem`, `*.key`, `.tts_vendor/`,
`.venv-tts/`, `*.deb`, editor lock files.

## Nothing removed
No files were deleted or moved. If any file's purpose is unclear to a future
reviewer, note it here rather than deleting — deletion requires confirming no
references first (`git grep <name>`).
