# archive/

One-off developer utilities and legacy files that are **not part of the running
application**. Verified to have **zero references** from application code, tests,
Docker, deploy scripts, and docs at the time of archival (repo audit, 2026-07).

They are kept here (rather than deleted) for historical reference and because
they are cheap to retain. Nothing in this folder is imported, served, scheduled,
or tested; it is excluded from pytest collection (`norecursedirs` in
`pytest.ini`).

| File | What it was | Why archived |
|------|-------------|--------------|
| `db_check_docs.py` | Ad-hoc DB doc inspector | Manual dev script, no callers |
| `db_list_docs.py` | Ad-hoc DB doc lister | Manual dev script, no callers |
| `docx_process_test.py` | Manual DOCX parsing check | Not a pytest test (0 tests collected), no callers |
| `build_multiagent_docs.py` | One-off HTML doc generator | Output already committed; generator unused |
| `activate_all_bots.py` / `.cmd` | Local helper to bulk-activate bots | Self-contained pair, unreferenced |
| `diagnose.cmd` | Windows local diagnostics launcher | Dev-only, unreferenced |
| `Buka AI Bisnis.vbs` | Windows double-click launcher | Dev-only, unreferenced |
| `api-docs.html` | Standalone static API doc page | Not served by `bn_platform/pages.py`, unreferenced |

To restore any file: `git mv archive/<file> ./`
