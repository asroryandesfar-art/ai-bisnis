# Top-1 Global Action Plan

The engineering is strong. The win now depends on **story + proof visibility**.
Highest ROI first.

## In the next 2 hours (must-do)
1. **Record the 2-minute demo video** using `docs/WINNER_DEMO_PLAYBOOK.md`.
   Climax = verifying a real deploy on cspr.live. This is the single biggest
   lever.
2. **Set GitHub metadata** (description, homepage, topics) — one command in the
   checklist. Makes the repo look finished at a glance.
3. **Paste BUIDL page copy** (`docs/BUIDL_PAGE_COPY.md`) into DoraHacks; fill the
   demo video + live URL links.
4. Add **2 screenshots** to README: dashboard + the Casper proof card.

## In the next 6 hours (should-do)
5. Merge this branch → main; confirm **CodeQL + CI are green** and **no
   High/Critical** in the Security tab.
6. Enable **Dependabot alerts** in repo settings.
7. Do a **fresh live smoke test**: register → chat → anchor → verify on cspr.live,
   exactly as a judge would. Fix any friction in the playbook.
8. Optionally record the **5-minute cut** for judges who want depth.

## Before you submit (final gate)
- [ ] Demo video link live and in README + BUIDL.
- [ ] Contract package hash + 2 tx hashes visible on BUIDL and in
      `CASPER_TESTNET_PROOFS.md`.
- [ ] GitHub description/topics/homepage set.
- [ ] CodeQL/Dependabot green; no High/Critical.
- [ ] README readable in 3 minutes; one-liner + Casper proof up top.
- [ ] Playbook reproduced end-to-end once (it actually works for a stranger).

## What must be in the demo video
- The one-liner in the first 15 seconds.
- One clear business decision by an agent.
- The Casper proof card with a Tx Hash.
- Live verification on cspr.live (status Success, casper-test).
- One sentence on security ("audited, hardened") + one on scale.

## What must be on the BUIDL page
- Problem → solution → key innovation (verifiable AI accountability).
- The testnet proof block (real hashes) with explorer links.
- Demo video + live URL + repo link.
- One "why this wins" paragraph (not marketing fluff).

## Do NOT do
- Do not fabricate hashes, metrics, or partnerships.
- Do not claim "100% secure" — say "security-hardened, audited."
- Do not over-explain the 20-agent internals in the video; show one clean flow.
- Do not show any secret/terminal/wallet key on screen.
- Do not do risky last-minute dependency upgrades before submission.

## Biggest risks
1. **No video** → judges undervalue the tech. Mitigation: record the 2-min cut now.
2. **Casper story under-sold** → looks like "AI + optional blockchain". Mitigation:
   make verification the demo climax; lead the README with it.
3. **Empty GitHub metadata / BUIDL** → looks unfinished. Mitigation: 15-minute fix.
4. **A judge can't reproduce the demo** → mitigated by the tester playbook; test it
   yourself once against the live URL.

## How to look strong fast
- Lead with proof, not claims: a one-click cspr.live verification beats any pitch.
- Show it's real: live URL + confirmed txs + passing tests + security audit.
- Keep the judge's path short: playbook → demo → verify. Three minutes to "I get it."
