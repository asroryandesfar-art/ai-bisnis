"""
agents/memory_agent.py — Memory Agent
Menyimpan, mengambil, dan merangkum memori percakapan lintas sesi.

Tiga lapisan memori:
  1. Short-term  — riwayat percakapan aktif (in-memory, hilang saat restart;
                   riwayat lengkapnya sudah ada permanen di tabel `messages`)
  2. Long-term   — fakta penting tentang user, disimpan di Postgres
                   (user_memory_profiles, conversation_memory_summaries) --
                   shared antar proses/worker, bukan file JSON lokal lagi
  3. Semantic    — embedding untuk cari memori relevan (opsional, pakai Pinecone)
"""
from __future__ import annotations

import json
import re
import hashlib
import logging
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any

import asyncpg

from base import BaseAgent, AgentResult

logger = logging.getLogger(__name__)


# ─── DATA CLASSES ─────────────────────────────────────────────

@dataclass
class ShortTermMemory:
    """Riwayat percakapan aktif — max N pesan terakhir."""
    conversation_id: str
    messages:        list[dict] = field(default_factory=list)
    created_at:      str = field(default_factory=lambda: _now())
    last_updated:    str = field(default_factory=lambda: _now())

    def add(self, role: str, content: str, meta: dict = None):
        self.messages.append({
            "role":    role,
            "content": content,
            "ts":      _now(),
            "meta":    meta or {},
        })
        self.last_updated = _now()

    def get_recent(self, n: int = 10) -> list[dict]:
        return self.messages[-n:]

    def trim(self, max_messages: int = 50):
        if len(self.messages) > max_messages:
            self.messages = self.messages[-max_messages:]


@dataclass
class LongTermFact:
    """Satu fakta yang diingat tentang user atau konteks."""
    key:        str           # e.g. "user_name", "preferred_language", "last_order_id"
    value:      Any
    confidence: float = 1.0  # 0.0-1.0
    source:     str   = "extracted"  # "extracted" | "explicit" | "inferred"
    created_at: str   = field(default_factory=lambda: _now())
    updated_at: str   = field(default_factory=lambda: _now())
    times_used: int   = 0

    def use(self):
        self.times_used += 1
        self.updated_at = _now()


@dataclass
class UserProfile:
    """Profil user yang dibangun dari akumulasi percakapan."""
    user_id:     str
    org_id:      str
    bot_id:      str
    facts:       dict[str, LongTermFact] = field(default_factory=dict)
    total_convs: int = 0
    created_at:  str = field(default_factory=lambda: _now())
    updated_at:  str = field(default_factory=lambda: _now())

    def set_fact(self, key: str, value: Any, confidence: float = 1.0, source: str = "extracted"):
        if key in self.facts:
            self.facts[key].value      = value
            self.facts[key].confidence = confidence
            self.facts[key].updated_at = _now()
        else:
            self.facts[key] = LongTermFact(
                key=key, value=value,
                confidence=confidence, source=source,
            )
        self.updated_at = _now()

    def get_fact(self, key: str) -> Any | None:
        f = self.facts.get(key)
        if f:
            f.use()
            return f.value
        return None

    def to_context_string(self) -> str:
        """Format fakta sebagai teks untuk system prompt."""
        if not self.facts:
            return ""
        lines = ["## Informasi yang diketahui tentang user ini:"]
        for k, f in self.facts.items():
            if f.confidence >= 0.6:
                lines.append(f"- {k}: {f.value} (confidence: {f.confidence:.0%})")
        return "\n".join(lines)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ─── MEMORY STORE ─────────────────────────────────────────────

class MemoryStore:
    """
    Long-term memory (fakta user + ringkasan percakapan) disimpan di Postgres
    (tabel user_memory_profiles / conversation_memory_summaries) ketika
    caller menyediakan `pool` -- shared antar semua proses/worker BotNesia,
    bukan file JSON lokal per-proses lagi. SELALU baca langsung dari DB
    (tidak ada cache di proses ini) supaya tidak ada celah "lost update"
    seperti yang ada di pendekatan file lama.

    Kalau caller TIDAK menyediakan pool (mis. unit test ringan tanpa DB),
    fallback ke dict in-process biasa -- berguna untuk tetap bisa dites
    tanpa Postgres, tapi TIDAK persisten lintas proses/restart.

    Short-term memory (buffer percakapan aktif) selalu in-process saja,
    sengaja tidak persisten -- riwayat lengkapnya sudah ada permanen di
    tabel `messages`.
    """

    def __init__(self):
        self._short: dict[str, ShortTermMemory] = {}       # conv_id → STM
        self._long:  dict[str, UserProfile]     = {}       # fallback tanpa pool
        self._summaries: dict[str, str]         = {}       # fallback tanpa pool

    def _user_key(self, user_id: str, org_id: str, bot_id: str) -> str:
        return hashlib.md5(f"{org_id}:{bot_id}:{user_id}".encode()).hexdigest()

    # ── Short-term ──────────────────────────────────────────────

    def get_stm(self, conv_id: str) -> ShortTermMemory:
        if conv_id not in self._short:
            self._short[conv_id] = ShortTermMemory(conversation_id=conv_id)
        return self._short[conv_id]

    def add_to_stm(self, conv_id: str, role: str, content: str, meta: dict = None):
        stm = self.get_stm(conv_id)
        stm.add(role, content, meta)
        stm.trim(max_messages=60)

    def clear_stm(self, conv_id: str):
        self._short.pop(conv_id, None)

    # ── Long-term ───────────────────────────────────────────────

    async def get_profile(self, user_id: str, org_id: str, bot_id: str,
                           pool: asyncpg.Pool | None = None) -> UserProfile:
        if pool is None:
            key = self._user_key(user_id, org_id, bot_id)
            if key not in self._long:
                self._long[key] = UserProfile(user_id=user_id, org_id=org_id, bot_id=bot_id)
            return self._long[key]

        row = await pool.fetchrow(
            """SELECT facts, total_convs, created_at, updated_at FROM user_memory_profiles
               WHERE org_id=$1 AND bot_id=$2 AND end_user_id=$3""",
            org_id, bot_id, user_id,
        )
        profile = UserProfile(user_id=user_id, org_id=org_id, bot_id=bot_id)
        if row:
            facts = row["facts"]
            if isinstance(facts, str):
                try:
                    facts = json.loads(facts)
                except (TypeError, ValueError):
                    facts = {}
            for fk, fv in (facts or {}).items():
                profile.facts[fk] = LongTermFact(**fv)
            profile.total_convs = row["total_convs"]
            profile.created_at = str(row["created_at"])
            profile.updated_at = str(row["updated_at"])
        return profile

    async def _persist_profile(self, profile: UserProfile, pool: asyncpg.Pool | None) -> None:
        if pool is None:
            key = self._user_key(profile.user_id, profile.org_id, profile.bot_id)
            self._long[key] = profile
            return
        facts_json = json.dumps({fk: asdict(fv) for fk, fv in profile.facts.items()})
        await pool.execute(
            """INSERT INTO user_memory_profiles (org_id, bot_id, end_user_id, facts, total_convs, updated_at)
               VALUES ($1,$2,$3,$4::jsonb,$5,NOW())
               ON CONFLICT (org_id, bot_id, end_user_id) DO UPDATE SET
                 facts=EXCLUDED.facts, total_convs=EXCLUDED.total_convs, updated_at=NOW()""",
            profile.org_id, profile.bot_id, profile.user_id, facts_json, profile.total_convs,
        )

    async def apply_fact_updates(self, user_id: str, org_id: str, bot_id: str, *,
                                  facts_to_store: list[dict], forget_keys: list[str],
                                  pool: asyncpg.Pool | None = None) -> UserProfile:
        """Baca profil sekali, terapkan facts_to_store + forget_keys, simpan sekali --
        menghindari beberapa round-trip read-modify-write terpisah yang bisa
        saling menimpa (tiap get_profile() di atas selalu baca fresh dari DB)."""
        profile = await self.get_profile(user_id, org_id, bot_id, pool=pool)
        for fact in facts_to_store:
            profile.set_fact(
                fact["key"], fact["value"],
                fact.get("confidence", 0.8), fact.get("source", "extracted"),
            )
        for key in forget_keys:
            profile.facts.pop(key, None)
        await self._persist_profile(profile, pool)
        return profile

    async def touch_profile_conv_count(self, user_id: str, org_id: str, bot_id: str,
                                        pool: asyncpg.Pool | None = None) -> UserProfile:
        profile = await self.get_profile(user_id, org_id, bot_id, pool=pool)
        profile.total_convs += 1
        await self._persist_profile(profile, pool)
        return profile

    # ── Conversation summary (PROMPT 5 context memory) ─────────────

    async def get_conversation_summary(self, conv_id: str, pool: asyncpg.Pool | None = None) -> str:
        if pool is None:
            return self._summaries.get(conv_id, "")
        return await pool.fetchval(
            "SELECT summary FROM conversation_memory_summaries WHERE conversation_id=$1", conv_id,
        ) or ""

    async def set_conversation_summary(self, conv_id: str, summary: str,
                                        pool: asyncpg.Pool | None = None) -> None:
        if not conv_id or not summary:
            return
        if pool is None:
            self._summaries[conv_id] = summary
            return
        await pool.execute(
            """INSERT INTO conversation_memory_summaries (conversation_id, summary, updated_at)
               VALUES ($1,$2,NOW())
               ON CONFLICT (conversation_id) DO UPDATE SET summary=EXCLUDED.summary, updated_at=NOW()""",
            conv_id, summary,
        )

    def stats(self) -> dict:
        return {
            "active_conversations":  len(self._short),
            "user_profiles_cached":  len(self._long),
            "conversation_summaries_cached": len(self._summaries),
        }


# ─── MEMORY AGENT ─────────────────────────────────────────────

# Singleton store — shared across all instances dalam satu proses. Tidak
# menyimpan pool sendiri -- pool dilewatkan per-panggilan (lihat MemoryAgent)
# karena store ini dibuat sebelum pool DB tersedia (saat SupervisorAgent
# pertama kali di-construct, sebelum request pertama masuk).
_global_store: MemoryStore | None = None

def get_memory_store() -> MemoryStore:
    global _global_store
    if _global_store is None:
        _global_store = MemoryStore()
    return _global_store


class MemoryAgent(BaseAgent):
    """
    Memory Agent melakukan dua hal:
    1. READ  — sebelum CS Agent: ambil memori relevan & inject ke context
    2. WRITE — setelah Supervisor: ekstrak fakta baru dari percakapan
    """
    name = "memory_agent"
    system_prompt = """Kamu adalah Memory Agent dalam sistem multi-agent BotNesia.

Tugasmu: Ekstrak fakta penting dari percakapan yang harus diingat untuk sesi berikutnya.

Fakta yang perlu diekstrak (jika ada):
- Identitas: nama, email, nomor HP
- Preferensi: bahasa, cara komunikasi, topik yang disukai
- Konteks bisnis: nama perusahaan, industri, ukuran tim
- Target/tujuan bisnis (key: "business_goal", contoh value: "naikkan omzet 20% dalam 3 bulan")
- Riwayat penting: nomor order, masalah yang pernah terjadi, solusi yang berhasil
- Pola perilaku: jam aktif, frekuensi komplain, topik berulang

Output WAJIB format JSON:
{
  "facts_to_store": [
    {"key": "user_name", "value": "Budi Santoso", "confidence": 0.95, "source": "explicit"},
    {"key": "prefers_formal_tone", "value": true, "confidence": 0.7, "source": "inferred"},
    {"key": "last_complaint_topic", "value": "keterlambatan pengiriman", "confidence": 1.0, "source": "extracted"}
  ],
  "summary": "Ringkasan kumulatif percakapan ini (gabungan ringkasan sebelumnya + turn terbaru), 2-4 kalimat",
  "forget_keys": []
}

Aturan:
- Hanya simpan fakta yang benar-benar berguna untuk percakapan mendatang
- confidence: 0.0-1.0
- source: "explicit" (user sebut langsung) | "extracted" (dari konteks) | "inferred" (kesimpulan)
- forget_keys: daftar key yang harus dihapus (user koreksi info lama)
- Jika tidak ada fakta yang perlu disimpan, kembalikan facts_to_store: []
- JANGAN simpan data sensitif (password, OTP, PIN, nomor kartu/CVV, token API) ke dalam facts_to_store atau summary"""

    def __init__(
        self,
        api_key: str,
        model: str | None = None,
        base_url: str | None = None,
        app_url: str = "https://botnesia.id",
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            app_url=app_url,
        )
        self.store = get_memory_store()

    # ── READ: inject memori ke context ──────────────────────────

    async def enrich_context(self, context: dict) -> dict:
        """
        Panggil ini SEBELUM Supervisor.process() untuk inject memori.
        Return context yang sudah diperkaya dengan memori.

        Pool DB diambil dari context["_observability_pool"] (sudah dilewatkan
        oleh main.py /chat handler ke trace_request()/supervisor.process())
        -- kalau tidak ada (mis. unit test ringan), fallback ke dict
        in-process di MemoryStore (tidak persisten lintas proses).
        """
        conv_id = context.get("conversation_id", "")
        user_id = context.get("user_id") or context.get("metadata", {}).get("userId", "anonymous")
        org_id  = context.get("org_id", "")
        bot_id  = context.get("bot_id", "")
        pool    = context.get("_observability_pool")

        enriched = dict(context)

        # 1. Short-term: tambahkan pesan user terbaru ke STM
        user_msg = context.get("user_message", "")
        if user_msg and conv_id:
            self.store.add_to_stm(conv_id, "user", user_msg)

        # 2. Long-term: inject profil user ke knowledge_base_context
        if user_id and user_id != "anonymous":
            profile = await self.store.get_profile(user_id, org_id, bot_id, pool=pool)
            profile_ctx = profile.to_context_string()
            if profile_ctx:
                existing_kb = enriched.get("knowledge_base_context", "")
                enriched["knowledge_base_context"] = (
                    profile_ctx + "\n\n" + existing_kb
                ).strip()

        # 2.5 Ringkasan percakapan: beri kesinambungan untuk follow-up
        # (mis. "Kalau yang Pro gimana?" setelah membahas paket sebelumnya).
        if conv_id:
            summary = await self.store.get_conversation_summary(conv_id, pool=pool)
            if summary:
                existing_kb = enriched.get("knowledge_base_context", "")
                enriched["knowledge_base_context"] = (
                    f"## Ringkasan percakapan sejauh ini\n{summary}\n\n" + existing_kb
                ).strip()

        # 3. Tandai user_id di context
        enriched["_memory_user_id"] = user_id
        return enriched

    # ── WRITE: ekstrak & simpan fakta baru ──────────────────────

    def _extract_fallback_facts(self, user_msg: str) -> list[dict]:
        """Deterministic fallback for explicit facts when the LLM extractor is unavailable."""
        text = (user_msg or "").strip()
        facts: list[dict] = []

        if re.match(r"^\s*(?:ingat|remember)\b", text, flags=re.IGNORECASE):
            return []

        name_match = re.search(
            r"\b(?:nama saya|saya bernama|my name is|i am|i'm)\s+([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,60})",
            text,
            flags=re.IGNORECASE,
        )
        if name_match:
            name = re.split(r"\s+(?:dan|and|,|\. )\b", name_match.group(1).strip(), maxsplit=1)[0].strip(" .,")
            if name:
                facts.append({"key": "user_name", "value": name, "confidence": 0.9, "source": "explicit_fallback"})

        business_match = re.search(
            r"\b(?:punya|memiliki|owner of|have|run)\s+(?:usaha|bisnis|toko|business|store)?\s*([A-Za-zÀ-ÿ][A-Za-zÀ-ÿ .'-]{1,80})",
            text,
            flags=re.IGNORECASE,
        )
        if business_match:
            business = business_match.group(1).strip(" .,;:")
            if business:
                facts.append({"key": "business_type", "value": business, "confidence": 0.75, "source": "explicit_fallback"})

        return facts

    async def run(self, context: dict) -> AgentResult:
        """
        Dipanggil SETELAH Supervisor.process().
        Ekstrak fakta dari percakapan dan simpan ke long-term memory.
        """
        user_msg     = context.get("user_message", "")
        bot_response = context.get("bot_response", "")
        history      = context.get("messages", [])
        user_id      = context.get("_memory_user_id") or \
                       context.get("metadata", {}).get("userId", "anonymous")
        org_id       = context.get("org_id", "")
        bot_id       = context.get("bot_id", "")
        conv_id      = context.get("conversation_id", "")
        pool         = context.get("_observability_pool")

        # Simpan respons bot ke STM
        if bot_response and conv_id:
            self.store.add_to_stm(conv_id, "assistant", bot_response)

        # Tidak perlu ekstrak untuk user anonim
        if user_id == "anonymous":
            return AgentResult(
                agent   = self.name,
                success = True,
                output  = {"skipped": True, "reason": "Anonymous user"},
                latency_ms = 0,
            )

        # Bangun teks percakapan untuk dianalisa
        history_text = "\n".join(
            f"{m['role'].upper()}: {m['content']}"
            for m in history[-8:]
        )

        profile = await self.store.get_profile(user_id, org_id, bot_id, pool=pool)
        existing_facts = "\n".join(f"- {k}: {v.value}" for k, v in profile.facts.items()) or "Belum ada."
        previous_summary = await self.store.get_conversation_summary(conv_id, pool=pool) or "Belum ada."

        prompt = f"""Analisa percakapan berikut dan ekstrak fakta yang perlu diingat.

FAKTA YANG SUDAH TERSIMPAN:
{existing_facts}

RINGKASAN PERCAKAPAN SEBELUMNYA:
{previous_summary}

PERCAKAPAN TERBARU:
{history_text}

USER: {user_msg}
BOT: {bot_response}

Ekstrak fakta BARU atau UPDATE fakta yang sudah ada dalam format JSON. Untuk "summary",
gabungkan ringkasan sebelumnya dengan informasi baru dari turn ini menjadi satu ringkasan
kumulatif (jangan hanya meringkas turn ini saja)."""

        output = await self._call_llm_json(
            [
                {"role": "system", "content": self.system_prompt},
                {"role": "user", "content": prompt},
            ],
            temperature=0.1,
            default={"facts_to_store": [], "summary": "", "forget_keys": []},
        )
        if output.pop("_llm_unavailable", False):
            fallback_facts = self._extract_fallback_facts(user_msg)
            if fallback_facts:
                profile = await self.store.apply_fact_updates(
                    user_id, org_id, bot_id,
                    facts_to_store=fallback_facts, forget_keys=[], pool=pool,
                )
                if conv_id:
                    fallback_summary = previous_summary if previous_summary != "Belum ada." else ""
                    new_summary = " ".join(
                        part for part in [fallback_summary, user_msg.strip(), bot_response.strip()] if part
                    ).strip()
                    if new_summary:
                        await self.store.set_conversation_summary(conv_id, new_summary, pool=pool)
                profile = await self.store.touch_profile_conv_count(user_id, org_id, bot_id, pool=pool)
                return AgentResult(
                    agent=self.name,
                    success=True,
                    output={
                        "fallback": True,
                        "reason": "LLM provider unavailable; stored explicit facts with deterministic fallback",
                        "facts_stored": len(fallback_facts),
                        "facts_deleted": 0,
                        "user_profile": {
                            "user_id": user_id,
                            "total_convs": profile.total_convs,
                            "known_facts": len(profile.facts),
                        },
                    },
                    latency_ms=0,
                )
            logger.warning(
                "Memory write deferred because the LLM provider is unavailable "
                "(conversation_id=%s, org_id=%s)",
                conv_id,
                org_id,
            )
            return AgentResult(
                agent=self.name,
                success=True,
                output={
                    "skipped": True,
                    "reason": "Memory write deferred: LLM provider unavailable after retries",
                    "facts_stored": 0,
                    "facts_deleted": 0,
                },
                latency_ms=0,
            )

        # Simpan fakta baru + hapus fakta yang diminta dalam satu read-modify-write
        # (apply_fact_updates membaca profil fresh sendiri, jangan pakai `profile`
        # di atas yang sudah dibaca sebelum prompt LLM dikirim -- bisa stale).
        facts_to_store = [
            f for f in output.get("facts_to_store", [])
            if f.get("key") and f.get("value") is not None
        ]
        forget_keys = output.get("forget_keys", [])
        if facts_to_store or forget_keys:
            profile = await self.store.apply_fact_updates(
                user_id, org_id, bot_id,
                facts_to_store=facts_to_store, forget_keys=forget_keys, pool=pool,
            )
        stored_count = len(facts_to_store)

        # Simpan ringkasan kumulatif percakapan untuk follow-up berikutnya
        new_summary = str(output.get("summary") or "").strip()
        if new_summary and conv_id:
            await self.store.set_conversation_summary(conv_id, new_summary, pool=pool)

        # Update counter (read-modify-write fresh, lalu jadikan ini acuan untuk output)
        profile = await self.store.touch_profile_conv_count(user_id, org_id, bot_id, pool=pool)

        return AgentResult(
            agent   = self.name,
            success = True,
            output  = {
                "facts_stored":  stored_count,
                "facts_deleted": len(output.get("forget_keys", [])),
                "summary":       output.get("summary", ""),
                "user_profile":  {
                    "user_id":    user_id,
                    "total_convs": profile.total_convs,
                    "known_facts": len(profile.facts),
                },
            },
            latency_ms = 0,
        )
