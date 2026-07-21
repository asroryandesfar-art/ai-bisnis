"""policy_engine.engine — Policy Engine deklaratif (P1-C).

Satu titik keputusan governance untuk aksi agent:
  • tool berbahaya            → APPROVAL
  • domain blacklist          → BLOCK
  • biaya > limit             → APPROVAL
  • konten mengandung PII     → MASK (redaksi)

`PolicyEngine(rules)` — ruleset default + override per-org. Keputusan =
`Decision(action, reason, detail)`. Pure (tanpa I/O) → testable & dipakai di
banyak hook (tool_executor, web-intelligence, output, cost). Mandiri.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from urllib.parse import urlparse

ALLOW, BLOCK, APPROVAL, MASK = "allow", "block", "approval", "mask"

DEFAULT_RULES = {
    "dangerous_tools": ["run_command", "run_terminal", "write_file", "delete_file"],
    "blacklist_domains": [],          # mis. ["malware.test", "phishing.example"]
    "cost_limit_usd": None,           # None = tanpa batas
    "mask_pii": True,
}

# Pola PII (urutan penting: phone sebelum long_number agar digit telepon tak
# terbaca sebagai "nomor sensitif" generik).
_PII_PATTERNS = [
    ("email", re.compile(r"\b[\w.+-]+@[\w-]+\.[\w.-]+\b"), "[EMAIL]"),
    ("phone", re.compile(r"(?<!\d)(?:\+?62|0)8\d[\d\s.-]{6,12}\d"), "[PHONE]"),
    ("long_number", re.compile(r"(?<!\d)\d{13,19}(?!\d)"), "[SENSITIVE_NUMBER]"),
]


@dataclass
class Decision:
    action: str
    reason: str = ""
    detail: dict = field(default_factory=dict)

    @property
    def allowed(self) -> bool:
        return self.action == ALLOW


class PolicyEngine:
    def __init__(self, rules: dict | None = None):
        self.rules = {**DEFAULT_RULES, **(rules or {})}

    def check_tool(self, tool_name: str, *, approved: bool = False) -> Decision:
        if tool_name in set(self.rules.get("dangerous_tools") or []) and not approved:
            return Decision(APPROVAL, f"tool '{tool_name}' butuh approval", {"tool": tool_name})
        return Decision(ALLOW)

    def check_url(self, url: str) -> Decision:
        host = (urlparse(url).hostname or "").lower()
        for bad in self.rules.get("blacklist_domains") or []:
            b = str(bad).lower().lstrip(".")
            if b and (host == b or host.endswith("." + b)):
                return Decision(BLOCK, f"domain diblokir: {host}", {"domain": host})
        return Decision(ALLOW)

    def check_cost(self, cost_usd) -> Decision:
        limit = self.rules.get("cost_limit_usd")
        if limit is not None and cost_usd is not None and float(cost_usd) > float(limit):
            return Decision(APPROVAL, f"biaya {cost_usd} melebihi limit {limit}",
                            {"cost": float(cost_usd), "limit": float(limit)})
        return Decision(ALLOW)

    def mask(self, text: str) -> tuple[str, list[str]]:
        """Redaksi PII. Return (teks_ter-mask, jenis_yang_ditemukan)."""
        if not self.rules.get("mask_pii") or not text:
            return text, []
        out = text
        found: list[str] = []
        for name, pat, repl in _PII_PATTERNS:
            new = pat.sub(repl, out)
            if new != out:
                found.append(name)
            out = new
        return out, found

    def evaluate(self, *, kind: str, **kw) -> Decision:
        """Dispatch terpadu: kind ∈ {tool,url,cost}."""
        if kind == "tool":
            return self.check_tool(kw.get("tool_name", ""), approved=bool(kw.get("approved")))
        if kind == "url":
            return self.check_url(kw.get("url", ""))
        if kind == "cost":
            return self.check_cost(kw.get("cost_usd"))
        return Decision(ALLOW)
