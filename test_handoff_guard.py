"""
Unit tests for handoff_guard.py — single source of truth untuk kebijakan
"NEVER OFFER HUMAN HANDOFF UNLESS USER REQUESTS IT".

Mencakup seluruh skenario yang diizinkan (explicit human/admin/supervisor
request, refund, legal, billing dispute, account ownership) DAN skenario
yang TIDAK boleh memicu handoff (confidence rendah, "AI tidak tahu", error
AI, user marah/urgency tinggi tanpa permintaan eksplisit, banyak friction
point tanpa permintaan eksplisit) — plus regression test untuk bug nyata
yang ditemukan: kata "admin" salah memicu handoff saat muncul sebagai
substring di kata lain seperti "administrasi".
"""
import handoff_guard
from handoff_guard import is_handoff_allowed
from escalation import EscalationAgent
import asyncio


# ── 1. Skenario yang HARUS diizinkan (5 kategori) ──────────────────────────

def test_explicit_human_request_via_trigger_factor():
    allowed, category = is_handoff_allowed(
        trigger_factors=["request_human"], message="apa saja",
    )
    assert allowed is True
    assert category == "explicit_human_request"


def test_explicit_admin_request_via_keyword():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Saya mau bicara dengan admin",
    )
    assert allowed is True
    assert category == "explicit_human_request"


def test_explicit_supervisor_request():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Tolong sambungkan ke supervisor",
    )
    assert allowed is True
    assert category == "explicit_human_request"


def test_explicit_manusia_request():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Saya tidak mau bicara dengan bot, mau bicara manusia",
    )
    assert allowed is True
    assert category == "explicit_human_request"


def test_refund_request():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Saya mau minta refund pesanan kemarin",
    )
    assert allowed is True
    assert category == "refund"


def test_legal_threat():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Kalau tidak diselesaikan saya akan lapor polisi",
    )
    assert allowed is True
    assert category == "legal"


def test_billing_dispute():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Kenapa saya kena charge dua kali bulan ini?",
    )
    assert allowed is True
    assert category == "billing_dispute"


def test_account_ownership_issue():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Akun saya dibajak orang lain, tolong bantu",
    )
    assert allowed is True
    assert category == "account_ownership"


def test_trigger_factor_path_for_new_categories():
    """EscalationAgent trigger_factors juga harus diakui untuk billing/account."""
    allowed_billing, cat_billing = is_handoff_allowed(
        trigger_factors=["billing_dispute"], message="tidak relevan",
    )
    allowed_account, cat_account = is_handoff_allowed(
        trigger_factors=["account_ownership"], message="tidak relevan",
    )
    assert (allowed_billing, cat_billing) == (True, "billing_dispute")
    assert (allowed_account, cat_account) == (True, "account_ownership")


# ── 2. Skenario yang TIDAK BOLEH memicu handoff ────────────────────────────

def test_angry_user_high_urgency_without_explicit_request_is_not_allowed():
    """User marah & urgency tinggi TANPA minta manusia -> AI wajib solve/explain dulu."""
    allowed, category = is_handoff_allowed(
        trigger_factors=["repeated_negative"],
        message="Aplikasi ini bodoh sekali, sudah 3 kali error terus!",
    )
    assert allowed is False
    assert category is None


def test_heavy_friction_without_explicit_request_is_not_allowed():
    allowed, category = is_handoff_allowed(
        trigger_factors=["technical", "repeated_negative", "urgency"],
        message="Errornya tidak hilang-hilang, capek saya",
    )
    assert allowed is False
    assert category is None


def test_low_confidence_ai_unsure_is_not_allowed():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Saya kurang yakin AI ini paham pertanyaan saya",
    )
    assert allowed is False
    assert category is None


def test_public_threat_alone_is_no_longer_allowed():
    """Ancaman viral/media TANPA permintaan eksplisit -> AI tangani dulu, bukan langsung handoff."""
    allowed, category = is_handoff_allowed(
        trigger_factors=["public_threat"], message="Saya akan posting ini di media sosial",
    )
    assert allowed is False
    assert category is None


def test_plain_question_is_not_allowed():
    allowed, category = is_handoff_allowed(trigger_factors=[], message="Apa itu Bitcoin?")
    assert allowed is False
    assert category is None


# ── 3. Regression: "admin" sebagai substring tidak boleh salah memicu ─────

def test_administrasi_word_does_not_falsely_trigger_handoff():
    """Bug nyata: 'admin' sebagai substring di 'administrasi' dulu memicu
    handoff palsu untuk pertanyaan bisnis yang sangat umum."""
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Biaya administrasi bulanan berapa ya?",
    )
    assert allowed is False
    assert category is None


def test_administrator_word_does_not_falsely_trigger_handoff():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="Saya administrator toko online, mau tanya soal stok",
    )
    assert allowed is False
    assert category is None


def test_standalone_admin_word_still_triggers():
    allowed, category = is_handoff_allowed(
        trigger_factors=[], message="tolong hubungi admin",
    )
    assert allowed is True
    assert category == "explicit_human_request"


# ── 4. Regression at the EscalationAgent source (escalation.py::hit()) ────

def test_escalation_agent_does_not_flag_administrasi_as_request_human():
    agent = EscalationAgent()
    result = asyncio.run(agent.run({
        "user_message": "Biaya administrasi bulanan berapa ya?",
        "messages": [],
        "cs_confidence": 0.9,
    }))
    assert "request_human" not in result.output["trigger_factors"]


def test_escalation_agent_flags_explicit_admin_request():
    agent = EscalationAgent()
    result = asyncio.run(agent.run({
        "user_message": "Saya mau bicara dengan admin",
        "messages": [],
        "cs_confidence": 0.9,
    }))
    assert "request_human" in result.output["trigger_factors"]


def test_escalation_agent_flags_billing_dispute():
    agent = EscalationAgent()
    result = asyncio.run(agent.run({
        "user_message": "Saya merasa tertagih dua kali bulan ini",
        "messages": [],
        "cs_confidence": 0.9,
    }))
    assert "billing_dispute" in result.output["trigger_factors"]


def test_escalation_agent_flags_account_ownership():
    agent = EscalationAgent()
    result = asyncio.run(agent.run({
        "user_message": "Akun saya dibajak orang lain",
        "messages": [],
        "cs_confidence": 0.9,
    }))
    assert "account_ownership" in result.output["trigger_factors"]
