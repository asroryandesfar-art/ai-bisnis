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
from urllib.parse import urljoin, urlparse, urlunparse

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
    # ── AI Agent Platform Tools ──────────────────────────────────────────────
    "calculator": {
        "category": "computation",
        "description": "Evaluasi ekspresi matematika aman (aritmatika, pangkat, modulo).",
        "available": True,
        "implementation": "action_executor._eval_math",
    },
    "terminal_execute": {
        "category": "system",
        "description": (
            "Eksekusi shell command (git, npm, python, docker, dll) dengan "
            "permission gate dan audit logging. Butuh izin run_terminal."
        ),
        "available": True,
        "implementation": "terminal_service.TerminalService.execute",
    },
    "file_read": {
        "category": "system",
        "description": "Baca file dari filesystem nyata (bukan knowledge base). Butuh izin read_files.",
        "available": True,
        "implementation": "file_system_service.FileSystemService.read_file",
    },
    "file_write": {
        "category": "system",
        "description": "Tulis file ke filesystem nyata. Butuh izin write_files.",
        "available": True,
        "implementation": "file_system_service.FileSystemService.write_file",
    },
    "file_list": {
        "category": "system",
        "description": "Daftar file/folder dalam direktori. Butuh izin read_files.",
        "available": True,
        "implementation": "file_system_service.FileSystemService.list_directory",
    },
    "webhook_call": {
        "category": "external_apis",
        "description": "Panggil webhook/REST API eksternal (HTTP). SSRF-safe.",
        "available": True,
        "implementation": "tool_executor._exec_webhook_call",
    },
    "action_execute": {
        "category": "orchestration",
        "description": (
            "Action Executor pipeline: Plan → Permission → Execute → Verify → Report. "
            "Untuk goal multi-langkah kompleks yang butuh beberapa tool."
        ),
        "available": True,
        "implementation": "action_executor.ActionExecutor.execute",
    },
    "computer_use": {
        "category": "computer_control",
        "description": (
            "Computer Use enterprise: browser automation + native app interaction "
            "(klik, isi form, screenshot, scrape). Butuh izin browser_access/browser_write."
        ),
        "available": True,
        "implementation": "computer_use_service.ComputerUseService",
    },
    "sandbox_execution": {
        "category": "system",
        "description": (
            "Eksekusi terisolasi di sandbox: temporary workspace, virtual filesystem, "
            "safe execution, rollback. Untuk task yang butuh isolasi."
        ),
        "available": True,
        "implementation": "sandbox_manager.SandboxManager",
    },
    "permission_manager": {
        "category": "security",
        "description": (
            "Enterprise permission model: Allow Once/Always/Deny per permission type "
            "(read_files, write_files, delete_files, run_terminal, browser_access, dll)."
        ),
        "available": True,
        "implementation": "permission_manager.PermissionManager",
    },
    "audit_logger": {
        "category": "observability",
        "description": "Audit trail semua aksi agent: action_type, target, status, approval, error.",
        "available": True,
        "implementation": "audit_logger.log_action",
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


def resolve_public_ips(host: str) -> list[str]:
    """Resolve hostname SATU kali → daftar IPv4/IPv6 publik unik. Kosong jika
    host tidak bisa di-resolve ATAU ADA satu pun IP yang privat/loopback/
    link-local/reserved/multicast/unspecified (fail-closed).

    Inti mitigasi L-05 (DNS-rebinding TOCTOU): IP di-resolve SEKALI di sini,
    lalu di-pin saat connect (lihat ``build_pinned_request``). Karena HTTP
    client tidak lagi me-re-resolve DNS sendiri, DNS server penyerang tidak
    bisa mengubah IP antara saat pengecekan & saat koneksi."""
    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for info in infos:
        try:
            ip = ipaddress.ip_address(info[4][0])
        except (ValueError, IndexError):
            return []
        if (ip.is_private or ip.is_loopback or ip.is_link_local
                or ip.is_reserved or ip.is_multicast or ip.is_unspecified):
            return []
        addr = info[4][0]
        if addr not in seen:
            seen.add(addr)
            out.append(addr)
    return out


def _is_public_host(host: str) -> bool:
    """False jika host me-resolve ke alamat privat/loopback/link-local/metadata."""
    return bool(resolve_public_ips(host))


class SSRFBlocked(Exception):
    """Host gagal validasi anti-SSRF (privat/tidak ter-resolve) sehingga
    tidak ada IP publik yang bisa di-pin."""


def build_pinned_request(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    *,
    headers: dict | None = None,
) -> httpx.Request:
    """Bangun ``httpx.Request`` anti-DNS-rebinding (L-05).

    Alur: host di-resolve sekali via ``resolve_public_ips`` (validasi publik),
    IP pertama yang lolos dipakai sebagai TUJUAN KONEKSI langsung (URL
    di-rewrite ke IP itu), sementara header ``Host`` + TLS SNI tetap memakai
    hostname asli. Dengan demikian ``httpx``/``httpcore`` tidak melakukan
    resolusi DNS kedua kali saat connect → menutup celah TOCTOU.

    Raise ``SSRFBlocked`` bila host privat/tidak ter-resolve (fail-closed)."""
    parsed = urlparse(url)
    scheme = parsed.scheme.lower()
    if scheme not in _ALLOWED_SCHEMES or not parsed.hostname:
        raise SSRFBlocked(f"Skema/host tidak diizinkan: {parsed.scheme} {parsed.hostname!r}")
    ips = resolve_public_ips(parsed.hostname)
    if not ips:
        raise SSRFBlocked(f"Host {parsed.hostname!r} privat atau tidak ter-resolve.")
    pinned_ip = ips[0]
    # Tetap sertakan port eksplisit bila ada di URL asli.
    netloc = pinned_ip if parsed.port is None else f"{pinned_ip}:{parsed.port}"
    ip_url = urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))
    req_headers = dict(headers or {})
    # Host header tetap hostname asli agar virtual-host routing & cert valid.
    host_header = parsed.hostname if parsed.port is None else f"{parsed.hostname}:{parsed.port}"
    req_headers["Host"] = host_header
    req = client.build_request(method, ip_url, headers=req_headers)
    # SNI untuk TLS handshake memakai hostname asli (bukan IP) → sertifikat
    # tervalidasi terhadap hostname, koneksi fisik ke IP ter-pin.
    req.extensions["sni_hostname"] = parsed.hostname
    return req


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
    ulang; ukuran respons dibatasi `_MAX_BYTES`. Sejak mitigasi L-05, host
    di-resolve SATU kali lalu IP-nya di-pin saat koneksi (DNS tidak di-query
    ulang oleh HTTP client) sehingga DNS-rebinding TOCTOU tertutup.
    """
    ok, reason = _validate_url(url)
    if not ok:
        return {"success": False, "url": url, "error": reason}

    current_url = url
    body = b""
    encoding = "utf-8"
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for _ in range(_MAX_REDIRECTS + 1):
                # L-05: bangun request ke IP ter-pin (bukan re-resolve DNS).
                try:
                    req = build_pinned_request(
                        client, "GET", current_url,
                        headers={"User-Agent": "BotNesiaBot/1.0"},
                    )
                except SSRFBlocked as exc:
                    return {"success": False, "url": url, "error": str(exc)}
                response = await client.send(req, stream=True)
                try:
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
                finally:
                    # Tutup streaming response agar koneksi kembali ke pool
                    # (juga saat redirect/continue/return lebih awal).
                    await response.aclose()
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
