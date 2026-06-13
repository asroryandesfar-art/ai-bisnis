"""
groq_knowledge.py — Ringkasan terkurasi dokumentasi resmi Groq + katalog model,
untuk BotNesia Knowledge System (Universal Knowledge Access Layer).

Sumber resmi (https://console.groq.com/docs): text-chat, models, tool-use,
reasoning, errors, rate-limits.

Modul ini TIDAK memanggil LLM dan TIDAK melakukan I/O. `build_groq_context()`
dipanggil dari `supervisor.py` (STEP 0.3) hanya saat pertanyaan tampak
menyangkut Groq API/model (`looks_like_groq_question`) — bukan disisipkan ke
setiap pesan, mengikuti prinsip "jangan selalu melakukan web search/lookup".

CATATAN KEJUJURAN: ringkasan & katalog model di bawah adalah distilasi dari
dokumentasi resmi pada saat modul ini ditulis dan BISA BERUBAH (model baru
rilis, model lama deprecated, angka rate limit berubah per tier). Untuk angka
pasti/model terbaru, GroqExpertAgent harus mengarahkan user ke
https://console.groq.com/docs/models dan https://console.groq.com/docs/rate-limits
(lihat GROQ_EXPERT_BLOCK & SOURCE_VERIFICATION_BLOCK di knowledge_access_engine).
"""
from __future__ import annotations


# ============================================================
# DETEKSI PERTANYAAN GROQ
# ============================================================

_GROQ_HINTS = (
    "groq", "llama-3", "llama 3", "gpt-oss", "qwen3", "qwen 3", "mixtral",
    "whisper", "rate limit", "rpm", "tpm", "rpd", "tpd", "token per menit",
    "429", "tool_use", "tool calling", "tool-calling", "function calling",
    "reasoning_effort", "context window", "model groq", "groq api",
    "groq cloud", "groqcloud",
)


def looks_like_groq_question(text: str) -> bool:
    """True jika pertanyaan tampak menyangkut Groq API atau model LLM Groq."""
    lower = (text or "").lower()
    return any(hint in lower for hint in _GROQ_HINTS)


# ============================================================
# TOPIK DOKUMENTASI — deteksi & blok konten
# ============================================================

_TOPIC_HINTS: dict[str, tuple[str, ...]] = {
    "rate_limits": (
        "rate limit", "rpm", "rpd", "tpm", "tpd", "429", "terlalu banyak request",
        "quota", "kuota api", "retry-after",
    ),
    "errors": (
        "error", "gagal", "kode 500", "kode 503", "kode 401", "kode 403",
        "timeout", "kode error", "status 4", "status 5",
    ),
    "tool_use": (
        "tool use", "tool calling", "tool-calling", "function calling",
        "tool_calls", "parallel tool",
    ),
    "reasoning": (
        "reasoning", "reasoning_effort", "reasoning_format", "berpikir",
        "chain of thought", "gpt-oss", "qwen",
    ),
    "text_chat": (
        "streaming", "stream", "json mode", "structured output",
        "response_format", "chat completion", "max_completion_tokens",
        "temperature", "top_p",
    ),
    "models": (
        "model apa", "model mana", "pilih model", "rekomendasi model",
        "model terbaik", "model groq", "context window", "model list",
        "daftar model", "ganti model", "model paling",
    ),
}


def select_groq_topics(text: str) -> list[str]:
    """Pilih topik dokumentasi Groq yang relevan untuk `text`.

    Default ke ["models"] jika tidak ada topik spesifik yang cocok — paling
    sering relevan untuk pertanyaan umum "model apa yang bagus untuk X".
    """
    lower = (text or "").lower()
    topics = [topic for topic, hints in _TOPIC_HINTS.items() if any(h in lower for h in hints)]
    return topics or ["models"]


GROQ_TOPIC_BLOCKS: dict[str, str] = {
    "text_chat": """## Groq Docs — Chat Completions API
Endpoint chat completions Groq menerima daftar `messages` (role "system"/"user"/
"assistant") secara kronologis, plus `model`. Parameter penting:
- `temperature` (0-1): makin tinggi makin variatif, makin rendah makin deterministik.
- `max_completion_tokens`: batas token output (prompt + completion berbagi limit model).
- `top_p`: nucleus sampling, mengatur keberagaman kandidat token.
- `stream`: jika true, jawaban dikirim bertahap (delta) — cocok untuk UX chat real-time.
- `stop`: daftar string yang menghentikan generasi saat muncul.
- `response_format`: aktifkan Structured Outputs (JSON sesuai skema) tanpa perlu
  validasi/retry manual — BotNesia memakai pola ini via `_call_llm_json`.""",
    "models": """## Groq Docs — Model & Pemilihan Model
Groq mengkategorikan model menjadi Production (stabil untuk live), Preview
(evaluasi, bisa dihentikan), dan Deprecated. Daftar model aktif terkini selalu
bisa diambil dari endpoint `GET https://api.groq.com/openai/v1/models`.
Lihat katalog model (MODEL_CATALOG) untuk rekomendasi berdasarkan use case
(kecepatan, biaya, reasoning, coding, customer service, audio, safety).
Catatan: daftar & kemampuan model berubah seiring waktu — untuk daftar paling
akurat, cek https://console.groq.com/docs/models.""",
    "tool_use": """## Groq Docs — Tool Use / Function Calling
Alur tool use: (1) kirim definisi tool via parameter `tools` (JSON schema:
nama fungsi, deskripsi, parameter), (2) model membalas dengan `tool_calls`
(id, nama fungsi, argumen), (3) aplikasi menjalankan tool dan mengirim hasil
sebagai pesan role "tool" dengan `tool_call_id` yang cocok, (4) model
memproses hasil dan memberi jawaban final atau memanggil tool lagi.
Semua model yang dihosting Groq mendukung tool use; model terbaru (Llama
3.3-70b-versatile, Qwen3-32b, GPT-OSS) mendukung **parallel tool calls**
(memanggil beberapa tool sekaligus) — penting untuk agentic workflow dengan
banyak langkah karena kecepatan inferensi Groq (ratusan-ribuan token/detik)
membuat banyak panggilan tool tetap responsif.
Selain "Local Tool Calling" (aplikasi mengelola loop sendiri — pola yang
dipakai BotNesia), Groq juga punya "Built-In Tools" (web search/code execution
dikelola Groq, satu panggilan API) dan "Remote MCP" (tool via MCP server).""",
    "reasoning": """## Groq Docs — Model Reasoning
Model reasoning di Groq (mis. GPT-OSS 20B/120B, Qwen3-32B, GPT-OSS-Safeguard
20B) mendukung `reasoning_effort` (low/medium/high, atau none/default untuk
Qwen3) untuk mengatur seberapa dalam model "berpikir" sebelum menjawab.
Untuk model non-GPT-OSS, `reasoning_format` mengatur tampilan reasoning:
`parsed` (reasoning di field `message.reasoning` terpisah, jawaban tetap
ringkas), `raw` (reasoning disisipkan dalam tag `<think>`), atau `hidden`
(hanya jawaban final). Model GPT-OSS memakai `include_reasoning` (true/false).
Best practice: gunakan `temperature` 0.5-0.7, naikkan `max_completion_tokens`
dari default 1024 untuk soal multi-langkah, taruh instruksi di pesan user
(bukan system prompt), dan hindari few-shot examples (zero-shot lebih baik
untuk model reasoning).""",
    "errors": """## Groq Docs — Error Handling
Kode error penting dari Groq API:
- 400 Bad Request: format request salah — validasi struktur request.
- 401 Unauthorized: API key tidak ada/tidak valid.
- 403 Forbidden: tidak punya akses ke resource.
- 404 Not Found: model/endpoint tidak ditemukan.
- 413 Payload Too Large: kurangi ukuran request (mis. potong konteks/prompt).
- 422 Unprocessable Entity: data request tidak valid secara semantik.
- 424 Failed Dependency: dependensi upstream gagal (umum untuk Remote MCP) —
  cek autentikasi rantai tool.
- 429 Too Many Requests: rate limit terlampaui — lihat blok Rate Limit.
- 498: kapasitas Flex tier penuh — coba lagi nanti.
- 500/502/503: error sisi server Groq — retry dengan backoff; tidak dikenakan
  biaya untuk error 5xx.
Respons error berisi JSON terstruktur dengan `message` dan `type` untuk
membantu debugging.""",
    "rate_limits": """## Groq Docs — Rate Limit & Reliability
Rate limit Groq diukur per organisasi (bukan per user) dalam beberapa dimensi:
RPM/RPD (request per menit/hari), TPM/TPD (token per menit/hari), ITPM/OTPM
(token input/output terpisah jika dikonfigurasi), ASH/ASD (detik audio per
jam/hari untuk model audio). Berlaku "limit pertama yang tercapai menang" —
mis. jika RPM=50 dan TPM=200K, begitu 50 request tercapai, limit berlaku
walau kuota token masih sisa. Token dari prompt caching TIDAK dihitung ke
rate limit.
Header response untuk memantau sisa kuota: `x-ratelimit-remaining-requests`,
`x-ratelimit-remaining-tokens`, `x-ratelimit-reset-requests`,
`x-ratelimit-reset-tokens`, dan `retry-after` (detik) saat 429 terjadi.
Saat 429: tunggu sesuai `retry-after`, lalu retry dengan backoff — pola ini
sudah diterapkan BotNesia sendiri di `_call_llm_json` (lihat catatan
Groq 429 di memori teknis proyek). Untuk kebutuhan lebih besar, ada plan
Developer (limit lebih tinggi) serta opsi Batch/Flex processing.""",
}


def build_groq_context(text: str) -> str:
    """Bangun blok konteks dokumentasi Groq yang relevan untuk `text`.

    Mengembalikan string kosong jika `text` tidak tampak menyangkut Groq —
    supaya konteks ini tidak disisipkan ke pertanyaan yang tidak relevan.
    """
    if not looks_like_groq_question(text):
        return ""
    topics = select_groq_topics(text)
    blocks = [GROQ_TOPIC_BLOCKS[t] for t in topics if t in GROQ_TOPIC_BLOCKS]
    if "models" not in topics:
        blocks.append(GROQ_TOPIC_BLOCKS["models"])
    blocks.append(_format_model_catalog())
    return "\n\n".join(blocks)


# ============================================================
# KATALOG MODEL — untuk rekomendasi pemilihan model
# ============================================================

MODEL_CATALOG: list[dict] = [
    {
        "id": "llama-3.1-8b-instant",
        "developer": "Meta",
        "context_window": 128000,
        "speed_tier": "tercepat",
        "cost_tier": "termurah",
        "best_for": ["customer_service", "speed", "cost"],
        "notes": (
            "Model kecil & sangat cepat — cocok untuk respons chat real-time "
            "bervolume tinggi, klasifikasi, ekstraksi singkat, dan FAQ sederhana."
        ),
    },
    {
        "id": "llama-3.3-70b-versatile",
        "developer": "Meta",
        "context_window": 128000,
        "speed_tier": "cepat",
        "cost_tier": "menengah",
        "best_for": ["customer_service", "general", "balanced"],
        "notes": (
            "Model serba guna — keseimbangan terbaik antara kualitas jawaban, "
            "kecepatan, dan biaya untuk customer service umum. Mendukung "
            "parallel tool calls."
        ),
    },
    {
        "id": "openai/gpt-oss-120b",
        "developer": "OpenAI (open-weight, hosted di Groq)",
        "context_window": 131072,
        "speed_tier": "sangat cepat (~500 tps)",
        "cost_tier": "menengah-tinggi",
        "best_for": ["reasoning", "coding", "complex_tasks", "agentic"],
        "notes": (
            "Model open-weight terbaru OpenAI dengan reasoning_effort "
            "(low/medium/high), built-in browser search & code execution. "
            "Pilihan terbaik untuk reasoning kompleks dan coding di Groq."
        ),
    },
    {
        "id": "openai/gpt-oss-20b",
        "developer": "OpenAI (open-weight, hosted di Groq)",
        "context_window": 131072,
        "speed_tier": "sangat cepat",
        "cost_tier": "menengah",
        "best_for": ["reasoning", "coding", "cost"],
        "notes": (
            "Versi lebih kecil dari GPT-OSS — tetap mendukung reasoning_effort, "
            "lebih hemat daripada versi 120B."
        ),
    },
    {
        "id": "qwen/qwen3-32b",
        "developer": "Alibaba (Qwen)",
        "context_window": 131072,
        "speed_tier": "cepat",
        "cost_tier": "menengah",
        "best_for": ["reasoning", "coding"],
        "notes": (
            "Model reasoning dengan opsi reasoning_effort (none/default), "
            "kuat untuk tugas logika & coding."
        ),
    },
    {
        "id": "groq/compound",
        "developer": "Groq (sistem agentic)",
        "context_window": None,
        "speed_tier": "sangat cepat (~450 tps)",
        "cost_tier": "menengah",
        "best_for": ["agentic", "web_search", "code_execution"],
        "notes": (
            "Sistem agentic dengan tool bawaan (web search, code execution) — "
            "cocok jika butuh agent yang bisa mencari info terbaru/eksekusi "
            "kode tanpa membangun tool-calling sendiri."
        ),
    },
    {
        "id": "whisper-large-v3-turbo",
        "developer": "OpenAI (hosted di Groq)",
        "context_window": None,
        "speed_tier": "sangat cepat",
        "cost_tier": "rendah",
        "best_for": ["audio"],
        "notes": "Transkripsi/translasi audio ke teks — untuk fitur voice/STT.",
    },
    {
        "id": "llama-guard-3-8b",
        "developer": "Meta",
        "context_window": 8192,
        "speed_tier": "cepat",
        "cost_tier": "rendah",
        "best_for": ["safety"],
        "notes": "Model moderasi/safety untuk memfilter konten berisiko.",
    },
]

_MODEL_BY_ID = {m["id"]: m for m in MODEL_CATALOG}

# Urutan prioritas rekomendasi per use case (id pertama = paling direkomendasikan).
_USE_CASE_PRIORITY: dict[str, list[str]] = {
    "speed": ["llama-3.1-8b-instant", "groq/compound", "llama-3.3-70b-versatile"],
    "reasoning": ["openai/gpt-oss-120b", "qwen/qwen3-32b", "openai/gpt-oss-20b"],
    "customer_service": ["llama-3.3-70b-versatile", "llama-3.1-8b-instant"],
    "coding": ["openai/gpt-oss-120b", "qwen/qwen3-32b"],
    "cost": ["llama-3.1-8b-instant", "openai/gpt-oss-20b"],
    "agentic": ["groq/compound", "openai/gpt-oss-120b"],
    "audio": ["whisper-large-v3-turbo"],
    "safety": ["llama-guard-3-8b"],
}


def recommend_model(use_case: str) -> dict:
    """Rekomendasikan model Groq untuk `use_case`.

    `use_case` salah satu dari: speed, reasoning, customer_service, coding,
    cost, agentic, audio, safety. Mengembalikan dict dengan `recommended`
    (entri MODEL_CATALOG) dan `alternatives` (list entri lain), atau
    `recommended=None` + `note` jika `use_case` tidak dikenali.
    """
    key = (use_case or "").strip().lower()
    ids = _USE_CASE_PRIORITY.get(key)
    if not ids:
        return {
            "use_case": key,
            "recommended": None,
            "alternatives": [],
            "note": (
                f"Use case '{use_case}' tidak dikenali. Pilihan yang tersedia: "
                + ", ".join(sorted(_USE_CASE_PRIORITY))
            ),
        }
    recommended = _MODEL_BY_ID.get(ids[0])
    alternatives = [_MODEL_BY_ID[i] for i in ids[1:] if i in _MODEL_BY_ID]
    return {"use_case": key, "recommended": recommended, "alternatives": alternatives, "note": ""}


def _format_model_catalog() -> str:
    lines = ["## Groq Docs — Katalog Model BotNesia (ringkasan, bisa berubah)"]
    for m in MODEL_CATALOG:
        ctx = f"{m['context_window']:,}" if m.get("context_window") else "-"
        lines.append(
            f"- `{m['id']}` ({m['developer']}) — context window: {ctx}, "
            f"kecepatan: {m['speed_tier']}, biaya: {m['cost_tier']}, "
            f"cocok untuk: {', '.join(m['best_for'])}. {m['notes']}"
        )
    return "\n".join(lines)


# ============================================================
# STYLE GUIDANCE — GroqExpertAgent
# ============================================================

GROQ_EXPERT_BLOCK = """## GroqExpertAgent — Panduan Jawab Pertanyaan Groq
Pertanyaan ini menyangkut Groq API/model. Gunakan dokumentasi & katalog model
di atas sebagai rujukan. Untuk pemilihan model, sebutkan model spesifik
(`id`) dan alasannya berdasarkan use case (kecepatan/biaya/reasoning/coding/
customer service). Untuk debugging error/rate limit, jelaskan arti kode/
header terkait dan langkah penanganannya. Karena daftar model & angka rate
limit bisa berubah, sebutkan bahwa angka di atas adalah ringkasan dan arahkan
user ke https://console.groq.com/docs untuk memastikan info terbaru."""
