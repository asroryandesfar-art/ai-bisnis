"""
tool_registry.py — Katalog sumber pengetahuan ("tools") BotNesia + Website Reader.

Bagian dari Universal Knowledge Access Layer. Modul ini TIDAK rebuild apa pun
yang sudah ada — `TOOL_REGISTRY` hanya mendokumentasikan tool yang sudah
diimplementasikan di modul lain (mis. `_retrieve_chunks` di `main.py`,
`news_fetcher.py`, `finance_fetcher.py`, `botnesia_knowledge.py`) plus tool
yang BELUM tersedia (api/CRM/DB connectors generik, web search bebas) —
ditandai jujur sebagai `available: False` dengan alasan, sesuai Truthfulness
Policy (`identity_agent.py`).

Satu kapabilitas baru di modul ini: `read_website()` — Website Reader yang
SSRF-safe untuk membaca URL spesifik yang dikirim pengguna (bukan free-form
web search, yang membutuhkan API key search engine yang belum dikonfigurasi).

Sejak Phase 2 ("Tool Framework"), katalog ini diperluas dari sumber
pengetahuan murni menjadi katalog tool universal: termasuk tool aksi/output
(channel_messaging, email_reader, document_generator) selain sumber
pengetahuan -- tetap tidak ada eksekusi otomatis di sini, hanya katalog.
"""
from __future__ import annotations

import html
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx


# ============================================================
# KNOWLEDGE PRIORITY — urutan sumber informasi (lihat spec)
# ============================================================

KNOWLEDGE_PRIORITY = [
    "user_context",
    "tenant_context",
    "self_knowledge",
    "tenant_knowledge",
    "connected_business_systems",
    "external_apis",
    "web_search",
]


# ============================================================
# TOOL REGISTRY — katalog sumber pengetahuan
# ============================================================

TOOL_REGISTRY: dict[str, dict] = {
    "memory": {
        "category": "user_context",
        "description": "Riwayat percakapan & ringkasan profil user.",
        "available": True,
        "implementation": "memory_agent.MemoryAgent",
    },
    "self_knowledge": {
        "category": "self_knowledge",
        "description": "Data akun tenant: paket, billing, usage, channel, perbandingan paket.",
        "available": True,
        "implementation": "botnesia_knowledge.build_self_knowledge_context",
    },
    "business_analytics": {
        "category": "self_knowledge",
        "description": "Ringkasan 30 hari conversation_analysis: sentiment, outcome, topik, friksi.",
        "available": True,
        "implementation": "botnesia_knowledge.build_business_context",
    },
    "knowledge_base_search": {
        "category": "tenant_knowledge",
        "description": "Hybrid search (keyword + embedding) atas dokumen/FAQ/SOP tenant.",
        "available": True,
        "implementation": "main._retrieve_chunks",
    },
    "document_reader": {
        "category": "tenant_knowledge",
        "description": "Ingest PDF/DOCX/TXT/Markdown/CSV menjadi knowledge base (klasifikasi, ringkasan, FAQ/SOP).",
        "available": True,
        "implementation": "knowledge_builder_agent.KnowledgeBuilderAgent",
    },
    "news_search": {
        "category": "web_search",
        "description": "Pencarian berita terkini via RSS feed untuk pertanyaan bertopik berita.",
        "available": True,
        "implementation": "news_fetcher.build_news_context",
    },
    "financial_data": {
        "category": "web_search",
        "description": "Harga crypto/saham real-time untuk pertanyaan harga pasar.",
        "available": True,
        "implementation": "finance_fetcher.fetch_crypto_quotes / fetch_stock_quotes",
    },
    "website_reader": {
        "category": "web_search",
        "description": "Membaca konten halaman web spesifik yang dikirim user (bukan free-form search).",
        "available": True,
        "implementation": "tool_registry.read_website",
    },
    "groq_docs_knowledge": {
        "category": "self_knowledge",
        "description": (
            "Ringkasan dokumentasi resmi Groq (chat API, model, tool use, reasoning, "
            "errors, rate limit) + katalog model untuk rekomendasi pemilihan model "
            "(GroqExpertAgent)."
        ),
        "available": True,
        "implementation": "groq_knowledge.build_groq_context / groq_knowledge.recommend_model",
    },
    "api_connectors": {
        "category": "external_apis",
        "description": "Konektor API bisnis eksternal generik milik tenant (mis. ERP/CRM custom).",
        "available": False,
        "unavailable_reason": "Belum ada konektor API generik untuk sistem eksternal tenant.",
    },
    "crm_connectors": {
        "category": "connected_business_systems",
        "description": "Integrasi CRM (HubSpot/Salesforce/dll).",
        "available": False,
        "unavailable_reason": (
            "Belum diimplementasikan — integrations_store.py saat ini hanya "
            "menyimpan kredensial channel (WhatsApp/Telegram/Gmail)."
        ),
    },
    "db_query_tools": {
        "category": "connected_business_systems",
        "description": "Query langsung ke database operasional tenant di luar BotNesia.",
        "available": False,
        "unavailable_reason": (
            "Belum diimplementasikan — BotNesia hanya membaca database "
            "internalnya sendiri (billing/usage/conversation_analysis via self_knowledge)."
        ),
    },
    "channel_messaging": {
        "category": "messaging",
        "description": (
            "Kirim pesan keluar ke WhatsApp/Instagram/Facebook/Telegram via "
            "konektor channel nyata (bukan stub). Catatan jujur: saat ini "
            "ChannelManager.send_message() hanya dipanggil dari 2 jalur -- "
            "auto-reply pesan masuk (webhook) dan balasan manual dashboard "
            "omnichannel -- BELUM ada jalur generik bagi agent AI manapun "
            "untuk mengirim pesan proaktif di luar dua flow tersebut."
        ),
        "available": True,
        "implementation": "bn_platform.channel_manager.ChannelManager.send_message",
    },
    "email_reader": {
        "category": "user_context",
        "description": (
            "Baca email Gmail masuk (polling unread, OAuth) dan masukkan ke "
            "pipeline chat. HANYA membaca/mark-as-read -- BotNesia TIDAK "
            "mengirim email keluar (scope OAuth gmail.send tidak diaktifkan)."
        ),
        "available": True,
        "implementation": "main._gmail_poll_loop / main._gmail_list_unread",
    },
    "document_generator": {
        "category": "content_generation",
        "description": (
            "Generate dokumen PDF/DOCX/XLSX/PPTX dari spesifikasi struktur "
            "(judul, bagian, tabel, dll), dipakai Multimedia Studio."
        ),
        "available": True,
        "implementation": "document_generator.generate_document",
    },
    "calendar": {
        "category": "connected_business_systems",
        "description": "Integrasi kalender eksternal (Google/Outlook Calendar).",
        "available": False,
        "unavailable_reason": (
            "Belum diimplementasikan — tidak ada integrasi Google/Outlook "
            "Calendar di codebase ini. 'Content calendar' di marketing_agent.py "
            "adalah metadata penjadwalan kampanye internal, bukan kalender "
            "eksternal yang terhubung."
        ),
    },
    "general_web_search": {
        "category": "web_search",
        "description": "Pencarian web bebas (search engine API) untuk topik di luar berita/finansial.",
        "available": False,
        "unavailable_reason": (
            "Sudah diimplementasikan via web_search_agent.search() (SearXNG "
            "primer, Tavily fallback) tapi SEARXNG_URL/SEARCH_API_KEY di .env "
            "saat ini kosong — belum dikonfigurasi, bukan belum dibangun."
        ),
        "implementation": "web_search_agent.search",
    },
}


def available_tools() -> list[str]:
    return [name for name, meta in TOOL_REGISTRY.items() if meta.get("available")]


def describe_tool(name: str) -> dict:
    return dict(TOOL_REGISTRY.get(name) or {})


def web_search_status(*, searxng_url: str = "", tavily_api_key: str = "") -> dict:
    """Cek ketersediaan general_web_search secara real-time dari config milik
    caller (mis. main.py's cfg) tanpa tool_registry.py mengimpor main.py
    (hindari circular import). Pure function, tidak melakukan I/O."""
    if searxng_url or tavily_api_key:
        return {"available": True, "reason": "SEARXNG_URL atau SEARCH_API_KEY terkonfigurasi."}
    return {
        "available": False,
        "reason": "SEARXNG_URL dan SEARCH_API_KEY kosong — general_web_search belum dikonfigurasi.",
    }


# ============================================================
# WEBSITE READER — SSRF-safe URL fetcher
# ============================================================

_ALLOWED_SCHEMES = {"http", "https"}
_MAX_BYTES = 200_000
_MAX_TEXT_CHARS = 4000
_TIMEOUT = 6.0
_MAX_REDIRECTS = 3


class _TextExtractor(HTMLParser):
    """Ekstrak judul + teks (tanpa script/style) dari HTML, secara minimal."""

    _SKIP_TAGS = {"script", "style", "noscript"}

    def __init__(self) -> None:
        super().__init__()
        self._chunks: list[str] = []
        self._title_chunks: list[str] = []
        self._in_title = False
        self._skip_depth = 0

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP_TAGS:
            self._skip_depth += 1
        if tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag in self._SKIP_TAGS and self._skip_depth:
            self._skip_depth -= 1
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._skip_depth:
            return
        text = data.strip()
        if not text:
            return
        if self._in_title:
            self._title_chunks.append(text)
        else:
            self._chunks.append(text)

    def get_text(self) -> str:
        return "\n".join(self._chunks)

    def get_title(self) -> str:
        return " ".join(self._title_chunks).strip()


def _is_public_host(host: str) -> bool:
    """False jika host me-resolve ke alamat privat/loopback/link-local/metadata."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return False
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except ValueError:
            return False
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast or ip.is_unspecified:
            return False
    return True


def _validate_url(url: str) -> tuple[bool, str]:
    parsed = urlparse(url)
    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return False, f"Skema URL '{parsed.scheme or '(kosong)'}' tidak didukung (hanya http/https)."
    if not parsed.hostname:
        return False, "URL tidak valid (tidak ada host)."
    if not _is_public_host(parsed.hostname):
        return False, "URL menunjuk ke alamat jaringan privat/internal dan tidak bisa diakses."
    return True, ""


async def read_website(url: str) -> dict:
    """Baca konten halaman web yang dikirim user.

    SSRF-safe: hanya host publik dengan skema http/https; redirect divalidasi
    ulang; ukuran respons dibatasi `_MAX_BYTES`. Catatan: tidak melindungi dari
    DNS rebinding (pengecekan IP dan koneksi aktual bisa beda waktu) — cukup
    untuk memblok target umum (localhost, jaringan privat, endpoint metadata
    cloud), bukan jaminan keamanan penuh.
    """
    ok, reason = _validate_url(url)
    if not ok:
        return {"success": False, "url": url, "error": reason}

    current_url = url
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                async with client.stream(
                    "GET", current_url, headers={"User-Agent": "BotNesiaBot/1.0"}
                ) as response:
                    if response.is_redirect:
                        location = response.headers.get("location")
                        if not location:
                            return {"success": False, "url": url, "error": "Redirect tanpa tujuan."}
                        next_url = urljoin(current_url, location)
                        ok, reason = _validate_url(next_url)
                        if not ok:
                            return {"success": False, "url": url, "error": reason}
                        current_url = next_url
                        continue

                    if response.status_code >= 400:
                        return {
                            "success": False, "url": url, "final_url": current_url,
                            "error": f"Halaman mengembalikan status {response.status_code}.",
                        }

                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type and "text/plain" not in content_type:
                        return {
                            "success": False, "url": url, "final_url": current_url,
                            "error": f"Tipe konten '{content_type or 'tidak diketahui'}' tidak didukung untuk dibaca.",
                        }

                    chunks: list[bytes] = []
                    total = 0
                    async for chunk in response.aiter_bytes():
                        chunks.append(chunk)
                        total += len(chunk)
                        if total >= _MAX_BYTES:
                            break
                    body = b"".join(chunks)[:_MAX_BYTES]
                    encoding = response.encoding or "utf-8"
                break
            else:
                return {"success": False, "url": url, "error": "Terlalu banyak redirect."}
    except httpx.HTTPError as exc:
        return {"success": False, "url": url, "error": f"Gagal mengambil halaman: {exc}"}

    text_body = body.decode(encoding, errors="ignore")
    extractor = _TextExtractor()
    extractor.feed(text_body)
    text = html.unescape(extractor.get_text())
    title = html.unescape(extractor.get_title())

    return {
        "success": True,
        "url": url,
        "final_url": current_url,
        "title": title[:300],
        "text": text[:_MAX_TEXT_CHARS],
    }
