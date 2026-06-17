"""
handoff_guard.py — Satu-satunya sumber kebenaran untuk kebijakan Human Handoff.

ATURAN GLOBAL (NEVER OFFER HUMAN HANDOFF UNLESS USER REQUESTS IT):
AI tidak pernah menawarkan/memicu handoff ke manusia KECUALI salah satu dari
kategori berikut benar-benar terdeteksi pada giliran ini:

  1. explicit_human_request — user secara eksplisit minta admin / manusia /
     customer service manusia / supervisor / manager.
  2. refund                 — permintaan refund / pengembalian uang.
  3. legal                  — indikasi ancaman/isu hukum (polisi, pengacara).
  4. billing_dispute        — keberatan/dispute soal tagihan (salah tagih,
     dobel charge, dll).
  5. account_ownership      — masalah kepemilikan/akses akun (akun dibajak,
     hilang akses, dll).

Confidence rendah, "AI tidak tahu", error internal AI, user marah/emosi,
urgency tinggi, atau banyak friction point BERTURUT-TURUT TANPA salah satu
kategori di atas BUKAN alasan untuk handoff — AI wajib coba
solve -> explain -> recommend -> clarify dulu sebelum (tidak) menawarkan
handoff.

Semua pemanggil (supervisor.py::route_intent, bn_platform/handoff.py) harus
memanggil `is_handoff_allowed()` di sini, bukan menduplikasi/menge-derive
ulang aturan ini sendiri.
"""

import re

EXPLICIT_HUMAN_REQUEST_TERMS = (
    "minta manusia", "bicara orang", "bicara dengan manusia", "bicara manusia",
    "tidak mau bot", "admin", "cs manusia", "customer service manusia",
    "hubungkan ke manusia", "hubungkan ke admin", "live agent", "human agent",
    "supervisor", "manager", "atasan", "bicara dengan admin", "panggil admin",
)

LEGAL_TERMS = (
    "polisi", "pengacara", "somasi", "tuntut hukum", "gugat", "ancaman hukum",
)

REFUND_TERMS = (
    "refund", "uang kembali", "pengembalian dana", "retur",
)

BILLING_DISPUTE_TERMS = (
    "salah tagih", "tagihan salah", "dispute tagihan", "double charge",
    "kena charge dua kali", "tertagih dua kali", "billing dispute",
    "transaksi ganda", "dikenakan biaya dua kali",
)

ACCOUNT_OWNERSHIP_TERMS = (
    "akun saya diambil", "akun saya dibajak", "akun dibajak", "akun diretas",
    "akun saya diretas", "akun saya hilang", "kehilangan akses akun",
    "ambil alih akun", "akun bukan milik saya", "ganti pemilik akun",
    "akun saya hacked", "lupa akses akun",
)

ALLOWED_CATEGORIES = (
    "explicit_human_request", "legal", "refund",
    "billing_dispute", "account_ownership",
)


def _matches_any(msg_l: str, terms: tuple[str, ...]) -> bool:
    """Word-boundary match — substring containment salah memicu mis. 'admin'
    cocok di dalam 'administrasi'. Lihat bug yang ditemukan di escalation.py."""
    return any(re.search(r"\b" + re.escape(t) + r"\b", msg_l) for t in terms)


def is_handoff_allowed(*, trigger_factors: list[str] | None,
                        message: str) -> tuple[bool, str | None]:
    """
    Tentukan apakah handoff ke manusia boleh ditawarkan untuk giliran ini.

    `trigger_factors` — sinyal dari EscalationAgent (request_human, legal_threat,
    refund, billing_dispute, account_ownership), dipakai sebagai sinyal sekunder.
    `message` — pesan user saat ini, dicek langsung dengan word-boundary
    matching supaya tidak ada false positive (lihat ALLOWED_CATEGORIES).

    Return (allowed, category) — category adalah salah satu dari
    ALLOWED_CATEGORIES bila allowed=True, else None.
    """
    trigger_factors = trigger_factors or []
    msg_l = (message or "").lower()

    if "request_human" in trigger_factors or _matches_any(msg_l, EXPLICIT_HUMAN_REQUEST_TERMS):
        return True, "explicit_human_request"
    if "legal_threat" in trigger_factors or _matches_any(msg_l, LEGAL_TERMS):
        return True, "legal"
    if "refund" in trigger_factors or _matches_any(msg_l, REFUND_TERMS):
        return True, "refund"
    if "billing_dispute" in trigger_factors or _matches_any(msg_l, BILLING_DISPUTE_TERMS):
        return True, "billing_dispute"
    if "account_ownership" in trigger_factors or _matches_any(msg_l, ACCOUNT_OWNERSHIP_TERMS):
        return True, "account_ownership"

    return False, None
