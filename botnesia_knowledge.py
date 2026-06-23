"""
botnesia_knowledge.py — BotNesia Self-Knowledge & Business Context

Pure data-formatting (tidak ada panggilan LLM): membangun blok konteks markdown
yang menjelaskan BotNesia sendiri (misi, fitur, navigasi dashboard), paket/usage/
billing/channel milik tenant pemilik bot, dan ringkasan performa bisnis 30 hari
terakhir. Dikonsumsi oleh `cs_agent` (jalur Standard, via `knowledge_base_context`)
dan lensa reasoning `self_knowledge`/`business` (jalur Pro).

Semua fungsi di sini AMAN dipanggil setiap chat — jika query DB gagal, kembalikan
string kosong agar pipeline chat tidak terganggu (degradasi sama seperti
`_retrieve_chunks`).
"""
from __future__ import annotations

import json

from bn_platform.billing import get_active_subscription, current_usage
from bn_platform.omnichannel import list_channel_accounts


BOTNESIA_OVERVIEW = """## Tentang BotNesia
BotNesia adalah platform AI Business Operating System: SaaS multi-tenant yang
memungkinkan setiap bisnis membuat AI Agent (chatbot AI) sendiri untuk melayani
pelanggan di berbagai channel (WhatsApp, Instagram, Telegram, Website, Email/Gmail).

Misi BotNesia: membantu UMKM dan bisnis di Indonesia memiliki asisten AI yang
mengerti bisnis mereka — menjawab pertanyaan pelanggan, membantu penjualan, dan
memberikan insight bisnis — tanpa perlu tim engineering sendiri.

Fitur utama di dashboard:
- **Agent**: kelola AI Agent (bot) — system prompt, bahasa, suhu jawaban, dan
  "Reasoning Mode" (Standard = jawaban cepat; Pro = analisis lebih mendalam,
  multi-agent, untuk pertanyaan kompleks).
- **Channel & Communication Center**: hubungkan bot ke WhatsApp, Instagram,
  Telegram, Website widget, atau Gmail/Email, plus analitik per channel
  (response rate, AI resolution rate, kepuasan pelanggan).
- **Knowledge Base & Auto Knowledge Builder**: unggah dokumen/FAQ/website —
  AI otomatis menyusun ringkasan/FAQ/SOP dari dokumen yang diunggah (tetap
  perlu di-review/approve manusia sebelum dipublikasikan).
- **Workflow Builder**: otomasi alur kerja tanpa coding (trigger → kondisi →
  agent → aksi), mirip n8n/Zapier.
- **AI Workforce**: 7 agent operasional bisnis untuk tim internal (bukan
  chatbot publik ke pelanggan) — Finance Agent (invoice/expense/laporan
  keuangan), Marketing Agent (konten & kampanye), HR Agent (rekrutmen &
  evaluasi karyawan), Operations Agent (monitoring workflow/SLA), Security
  Agent (scan keamanan), Executive Agent/AI Business Analyst (sintesis
  lintas-departemen, skor kesehatan perusahaan, analisis akar masalah &
  rencana aksi 7/30/90 hari), dan Workforce Orchestration (koordinasi tugas
  antar-agent dengan approval manusia).
- **Self-Learning Center**: AI mendeteksi pola sukses (pola penjualan,
  resolusi komplain) dari riwayat percakapan nyata; insight baru aktif
  setelah di-approve manusia.
- **Multimedia Studio**: generate & analisis gambar (vision AI), generate
  dokumen (PDF/DOCX/XLSX/PPTX).
- **Analytics & Executive Analytics**: statistik percakapan, sentimen
  pelanggan, topik populer, kualitas jawaban bot, dan grafik tren bisnis di
  Executive Center.
- **Pengaturan**: profil organisasi, anggota tim (Business/Enterprise),
  keamanan (RBAC, audit log, API key), dan konfigurasi umum akun.
- **Integrasi**: API access dan webhook untuk paket Business/Enterprise.
- **Tenant/Organisasi**: setiap akun BotNesia adalah satu tenant dengan paket,
  batas penggunaan (usage limit), dan billing-nya sendiri — terisolasi dari
  tenant lain.

Paket BotNesia: Free, Starter, Pro, Business, Enterprise — beda di jumlah AI
Agent, batas percakapan/bulan, channel yang bisa dihubungkan, knowledge base,
analytics, dan fitur tim/API."""


def _fmt_idr(amount) -> str:
    try:
        amount = int(amount)
    except (TypeError, ValueError):
        return str(amount)
    if amount <= 0:
        return "Gratis"
    return "Rp" + f"{amount:,}".replace(",", ".")


def _fmt_limit(value) -> str:
    try:
        value = int(value)
    except (TypeError, ValueError):
        return str(value)
    return "tanpa batas" if value < 0 else str(value)


def _load_features(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    try:
        return json.loads(raw or "{}")
    except Exception:
        return {}


_CHANNEL_LABELS = {
    "whatsapp": "WhatsApp",
    "telegram": "Telegram",
    "website": "Website",
    "instagram": "Instagram",
    "email": "Email",
    "gmail": "Gmail",
}


async def build_self_knowledge_context(pool, org_id: str, bot_id: str, bot_row: dict) -> str:
    """Bangun blok konteks 'siapa BotNesia & status akun tenant ini'.

    Tidak pernah raise — kegagalan DB menghasilkan string kosong.
    """
    try:
        sections: list[str] = [BOTNESIA_OVERVIEW]

        # ── Akun & Paket ─────────────────────────────────────
        sub = await get_active_subscription(pool, org_id)
        usage = await current_usage(pool, org_id)

        account_lines = ["## Akun & Paket Anda"]
        reasoning_mode = bot_row.get("reasoning_mode") or "standard"
        account_lines.append(
            f"- Reasoning Mode AI Agent ini: **{reasoning_mode}** "
            f"({'analisis mendalam multi-agent' if reasoning_mode == 'pro' else 'jawaban cepat untuk pertanyaan sederhana'})"
        )
        billing_status = bot_row.get("billing_status")
        if billing_status:
            account_lines.append(f"- Status billing organisasi: **{billing_status}**")

        if sub:
            plan_name = sub.get("plan_name") or sub.get("plan_key") or "-"
            account_lines.append(f"- Paket aktif: **{plan_name}**")
            account_lines.append(f"- Status subscription: {sub.get('status', '-')}")
            if sub.get("current_period_end"):
                account_lines.append(f"- Periode berlaku sampai: {sub['current_period_end']}")
            if sub.get("trial_ends_at"):
                account_lines.append(f"- Masa trial sampai: {sub['trial_ends_at']}")

            limits = {
                "Percakapan/bulan": ("conversations", "max_conversations_per_month"),
                "AI Agent": ("agents", "max_agents"),
                "Anggota tim": ("users", "max_users"),
                "Dokumen Knowledge Base": ("knowledge", "max_knowledge_docs"),
                "Channel terhubung": ("channels", "max_channels"),
            }
            account_lines.append("- Penggunaan bulan ini vs batas paket:")
            for label, (usage_key, limit_key) in limits.items():
                used = usage.get(usage_key, 0)
                limit = sub.get(limit_key, 0)
                account_lines.append(f"  - {label}: {used} / {_fmt_limit(limit)}")
        else:
            account_lines.append(
                "- Belum ada data subscription aktif untuk organisasi ini "
                "(kemungkinan masih memakai paket Free default)."
            )

        sections.append("\n".join(account_lines))

        # ── Channel terhubung ────────────────────────────────
        channels = await list_channel_accounts(pool, org_id)
        channel_lines = ["## Channel Terhubung"]
        if channels:
            for ch in channels:
                label = _CHANNEL_LABELS.get(ch.get("channel_type"), str(ch.get("channel_type")))
                state = "aktif" if ch.get("is_active") else "nonaktif/disconnect"
                channel_lines.append(
                    f"- {label} ({ch.get('display_name', '-')}): **{state}**"
                    + (f", terhubung sejak {ch['connected_at']}" if ch.get("connected_at") else "")
                )
        else:
            channel_lines.append(
                "- Belum ada channel yang terhubung. Hubungkan via menu "
                "Channel → Tambah Channel di dashboard."
            )
        sections.append("\n".join(channel_lines))

        # ── Perbandingan Paket ───────────────────────────────
        plan_rows = await pool.fetch(
            """SELECT key, name, price_monthly_idr, max_conversations_per_month,
                      max_agents, max_users, max_knowledge_docs, max_channels, features
               FROM plans WHERE is_active=TRUE ORDER BY sort_order"""
        )
        plan_lines = ["## Perbandingan Paket"]
        for p in plan_rows:
            features = _load_features(p["features"])
            highlights = features.get("highlights") or []
            plan_lines.append(
                f"- **{p['name']}** ({_fmt_idr(p['price_monthly_idr'])}/bulan): "
                f"{_fmt_limit(p['max_agents'])} AI Agent, "
                f"{_fmt_limit(p['max_conversations_per_month'])} percakapan/bulan, "
                f"{_fmt_limit(p['max_channels'])} channel, "
                f"{_fmt_limit(p['max_knowledge_docs'])} dokumen knowledge base"
                + (f". Fitur: {', '.join(highlights)}" if highlights else "")
            )
        sections.append("\n".join(plan_lines))

        return "\n\n".join(sections)
    except Exception:
        return ""


async def build_business_context(pool, org_id: str, bot_id: str) -> str:
    """Bangun ringkasan performa bisnis 30 hari terakhir dari `conversation_analysis`.

    Mengembalikan string kosong jika belum ada data (bot baru) atau query gagal —
    lensa `business` akan skip dengan aman.
    """
    try:
        stats = await pool.fetchrow(
            """SELECT
                 COUNT(*) AS total,
                 AVG(sentiment_score) AS avg_sentiment,
                 COUNT(*) FILTER (WHERE outcome = 'resolved')   AS resolved,
                 COUNT(*) FILTER (WHERE outcome = 'unresolved') AS unresolved,
                 COUNT(*) FILTER (WHERE outcome = 'abandoned')  AS abandoned,
                 COUNT(*) FILTER (WHERE outcome = 'escalated')  AS escalated,
                 COUNT(*) FILTER (WHERE lead_status != 'none')  AS leads
               FROM conversation_analysis
               WHERE bot_id = $1 AND analyzed_at >= NOW() - INTERVAL '30 days'""",
            bot_id,
        )
        if not stats or not stats["total"]:
            return ""

        lines = ["## Ringkasan Performa Bisnis (30 hari terakhir)"]
        lines.append(f"- Total percakapan dianalisis: {stats['total']}")
        if stats["avg_sentiment"] is not None:
            lines.append(f"- Rata-rata sentimen pelanggan: {float(stats['avg_sentiment']):.2f} (skala -1 s/d 1)")
        lines.append(
            f"- Outcome: {stats['resolved']} resolved, {stats['unresolved']} unresolved, "
            f"{stats['abandoned']} abandoned, {stats['escalated']} escalated"
        )
        lines.append(f"- Percakapan dengan sinyal lead/penjualan: {stats['leads']}")

        topic_rows = await pool.fetch(
            """SELECT t AS topic, COUNT(*) AS n
               FROM conversation_analysis, unnest(topics) AS t
               WHERE bot_id = $1 AND analyzed_at >= NOW() - INTERVAL '30 days'
               GROUP BY t ORDER BY n DESC LIMIT 5""",
            bot_id,
        )
        if topic_rows:
            lines.append(
                "- Topik paling sering dibahas: "
                + ", ".join(f"{r['topic']} ({r['n']}x)" for r in topic_rows)
            )

        friction_rows = await pool.fetch(
            """SELECT f AS friction, COUNT(*) AS n
               FROM conversation_analysis,
                    jsonb_array_elements_text(raw_metrics->'friction_points') AS f
               WHERE bot_id = $1 AND analyzed_at >= NOW() - INTERVAL '30 days'
               GROUP BY f ORDER BY n DESC LIMIT 5""",
            bot_id,
        )
        if friction_rows:
            lines.append(
                "- Friction point/keluhan yang paling sering muncul: "
                + ", ".join(f"{r['friction']} ({r['n']}x)" for r in friction_rows)
            )

        insight_rows = await pool.fetch(
            """SELECT i AS insight, COUNT(*) AS n
               FROM conversation_analysis,
                    jsonb_array_elements_text(raw_metrics->'product_insights') AS i
               WHERE bot_id = $1 AND analyzed_at >= NOW() - INTERVAL '30 days'
               GROUP BY i ORDER BY n DESC LIMIT 5""",
            bot_id,
        )
        if insight_rows:
            lines.append(
                "- Insight produk yang sering muncul dari pelanggan: "
                + ", ".join(f"{r['insight']} ({r['n']}x)" for r in insight_rows)
            )

        return "\n".join(lines)
    except Exception:
        return ""
