"""
knowledge_access_engine.py — Tool Selection, Source Verification & Knowledge
Conflict Detection untuk BotNesia (Universal Knowledge Access Layer).

Modul ini TIDAK memanggil LLM dan TIDAK melakukan I/O (kecuali
`format_website_reading`, yang hanya memformat hasil dari
`tool_registry.read_website`). `select_knowledge_sources()` adalah pemeriksaan
ringan yang dijalankan bersama `ReasoningController.analyze()`:

- Tool Selection: mencatat kategori sumber pengetahuan mana yang relevan untuk
  pertanyaan ini (memory / self_knowledge / tenant_knowledge / web_search
  berita/finansial / website reader) beserta alasannya — supaya BotNesia tidak
  "selalu" mengaktifkan web search, hanya saat relevan.
- Source Verification & Conflict Detection: blok instruksi yang selalu
  disisipkan ke `knowledge_base_context` agar CSAgent menyebut sumber,
  menyebut freshness data, dan tidak diam-diam memilih salah satu sumber bila
  ada pertentangan.
"""
from __future__ import annotations

import re

import groq_knowledge as gk


URL_PATTERN = re.compile(r"https?://[^\s<>\"']+", re.IGNORECASE)

# Heuristik kategori kebutuhan informasi — sengaja konservatif: pertanyaan
# umum hanya mendapatkan "tenant_knowledge" (selalu diperiksa karena murah),
# bukan web search.
_SELF_KNOWLEDGE_HINTS = (
    "paket saya", "paket kami", "plan saya", "billing", "tagihan", "invoice",
    "kuota", "limit", "sisa percakapan", "channel saya", "akun saya",
    "subscription", "berlangganan", "upgrade paket",
)
_NEWS_HINTS = (
    "berita", "kabar", "kabar terbaru", "hari ini", "kemarin", "minggu ini", "viral", "trending",
)
_FINANCE_HINTS = (
    "harga", "kurs", "btc", "bitcoin", "eth", "ethereum", "crypto", "kripto",
    "saham", "ihsg", "rupiah", "dolar", "usd",
)

# Frasa "freshness" — pertanyaan yang menyiratkan butuh info real-time
# (Real-Time Knowledge Layer). Sengaja terpisah dari _NEWS_HINTS/_FINANCE_HINTS
# supaya freshness yang TIDAK tercakup kategori berita/finansial bisa diarahkan
# ke web search umum (`web_search:general`).
FRESHNESS_HINTS = (
    "terbaru", "sekarang", "minggu ini", "bulan ini", "breaking news",
    "baru-baru ini", "update terbaru", "hari ini", "saat ini",
)


def is_freshness_query(text: str) -> bool:
    """True jika pertanyaan menyiratkan butuh data/informasi terkini."""
    lower = (text or "").lower()
    return any(hint in lower for hint in FRESHNESS_HINTS)


def select_knowledge_sources(text: str, history: list | None = None) -> dict:
    """Tentukan kategori sumber pengetahuan yang relevan untuk `text`.

    Tidak mengubah pipeline fetch yang sudah ada (KB hybrid search di
    main.py tetap selalu dijalankan, news/finance tetap digerbang oleh
    heuristik main.py sendiri) — ini hanya mencatat *alasan* sumber mana
    yang relevan, untuk transparansi (`reasoning_brief.knowledge_routing`)
    dan untuk mengaktifkan Website Reader saat user mengirim URL.
    """
    lower = (text or "").lower()
    has_history = bool(history)

    url_match = URL_PATTERN.search(text or "")
    detected_url = url_match.group(0).rstrip(".,);]>\"'") if url_match else None

    reasons: dict[str, str] = {}

    if has_history:
        reasons["memory"] = "ada riwayat percakapan sebelumnya yang mungkin relevan"

    reasons["tenant_knowledge"] = "knowledge base tenant selalu diperiksa untuk konteks bisnis"

    if any(hint in lower for hint in _SELF_KNOWLEDGE_HINTS):
        reasons["self_knowledge"] = "pertanyaan menyangkut akun/paket/billing/usage tenant"

    if any(hint in lower for hint in _NEWS_HINTS):
        reasons["web_search:news"] = "pertanyaan tampak menyangkut informasi terkini/berita"

    if any(hint in lower for hint in _FINANCE_HINTS):
        reasons["web_search:financial"] = "pertanyaan tampak menyangkut harga pasar/finansial"

    if gk.looks_like_groq_question(text or ""):
        reasons["self_knowledge:groq_docs"] = "pertanyaan tampak menyangkut Groq API atau model LLM Groq"

    if detected_url:
        reasons["web_search:website_reader"] = "pengguna menyertakan URL untuk dibaca"

    if (
        is_freshness_query(text)
        and "web_search:news" not in reasons
        and "web_search:financial" not in reasons
        and "web_search:website_reader" not in reasons
    ):
        reasons["web_search:general"] = (
            "pertanyaan menyiratkan butuh informasi terbaru tapi tidak spesifik "
            "berita/finansial — gunakan web search umum jika tersedia"
        )

    needs_fresh_data = any(key.startswith("web_search:") for key in reasons)

    return {
        "sources_considered": list(reasons.keys()),
        "detected_url": detected_url,
        "reasons": reasons,
        "needs_fresh_data": needs_fresh_data,
    }


# ============================================================
# STYLE GUIDANCE — Source Verification & Conflict Detection
# ============================================================

SOURCE_VERIFICATION_BLOCK = """## Source Verification & Knowledge Conflict
Sebelum menjawab dengan data dari luar percakapan ini (knowledge base tenant,
data akun/billing/usage, berita, data market/crypto, atau halaman web yang
dibaca):
- Sebutkan sumbernya secara wajar (nama dokumen, judul berita, atau URL),
  terutama jika user memintanya atau jika datanya bisa berubah cepat (harga,
  berita).
- Jika sumber memiliki tanggal/waktu, sebutkan freshness-nya (data per kapan)
  agar user tahu seberapa baru informasinya.
- Jika dua sumber memberi informasi yang BERBEDA atau bertentangan (mis.
  knowledge base tenant vs berita terbaru, atau dua sumber berita), JANGAN
  diam-diam memilih salah satu. Jelaskan perbedaannya, sebutkan kedua sumber,
  dan nyatakan ketidakpastian secara eksplisit.
- Jika tidak ada data eksternal yang relevan untuk pertanyaan ini, jawab
  berdasarkan pengetahuan internal dan knowledge base tenant seperti biasa —
  tidak setiap pertanyaan butuh sumber eksternal."""

REALTIME_KNOWLEDGE_BLOCK = """## Real-Time Knowledge Layer
Pertanyaan ini menyiratkan kebutuhan data terkini (mis. mengandung kata
"terbaru", "sekarang", "hari ini", "minggu ini", "bulan ini", "breaking news").
- Jika konteks di atas berisi data berita/finansial/web search yang relevan dan
  bertanggal, PRIORITASKAN itu dibanding pengetahuan internal/training data, dan
  sebutkan per kapan data tersebut (freshness).
- Jika TIDAK ada data real-time yang relevan tersedia di konteks untuk
  pertanyaan "apa yang terjadi sekarang/hari ini" semacam ini, katakan secara
  jujur bahwa BotNesia tidak memiliki akses real-time untuk topik ini saat ini —
  jangan menjawab seolah informasi training data adalah yang terbaru."""

WEBSITE_READER_BLOCK = """## Website Reader
Pengguna menyertakan URL dan halamannya sudah dibaca (lihat konteks "Konten
halaman web" di atas). Gunakan isinya sebagai referensi tambahan, sebutkan
bahwa informasi berasal dari halaman tersebut (sertakan URL-nya), dan terapkan
Truthfulness Policy: jika kontennya tidak relevan atau gagal dibaca, katakan
itu secara jujur — jangan mengarang isi halaman."""


def format_website_reading(result: dict) -> str:
    """Format hasil `tool_registry.read_website()` menjadi blok konteks."""
    if not result:
        return ""
    url = result.get("url") or ""
    if not result.get("success"):
        error = result.get("error") or "tidak diketahui"
        return f"## Konten halaman web ({url})\nGagal membaca halaman ini. Alasan: {error}"

    title = (result.get("title") or "").strip()
    text = (result.get("text") or "").strip()
    header = f"## Konten halaman web ({url})"
    if title:
        header += f"\nJudul: {title}"
    if not text:
        return f"{header}\nHalaman berhasil diakses tetapi tidak ada teks yang bisa diekstrak."
    return f"{header}\n\n{text}"
