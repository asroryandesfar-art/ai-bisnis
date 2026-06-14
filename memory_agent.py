"""
agents/memory_agent.py — Memory Agent
Menyimpan, mengambil, dan merangkum memori percakapan lintas sesi.

Tiga lapisan memori:
  1. Short-term  — riwayat percakapan aktif (in-memory, hilang saat restart)
  2. Long-term   — fakta penting tentang user (persisten via file JSON / DB)
  3. Semantic    — embedding untuk cari memori relevan (opsional, pakai Pinecone)
"""
from __future__ import annotations

import json
import hashlib
import os
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from base import BaseAgent, AgentResult


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
    In-memory store dengan opsional persistensi ke file JSON.
    Di production: ganti dengan Redis atau PostgreSQL.
    """

    def __init__(self, persist_path: str | None = None):
        self._short: dict[str, ShortTermMemory] = {}       # conv_id → STM
        self._long:  dict[str, UserProfile]     = {}       # user_key → UserProfile
        self._summaries: dict[str, str]         = {}       # conv_id → ringkasan kumulatif
        self._persist_path = Path(persist_path) if persist_path else None
        if self._persist_path:
            self._load()

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

    def get_profile(self, user_id: str, org_id: str, bot_id: str) -> UserProfile:
        key = self._user_key(user_id, org_id, bot_id)
        if key not in self._long:
            self._long[key] = UserProfile(
                user_id=user_id, org_id=org_id, bot_id=bot_id
            )
        return self._long[key]

    def set_fact(self, user_id: str, org_id: str, bot_id: str,
                 fact_key: str, value: Any, confidence: float = 1.0, source: str = "extracted"):
        profile = self.get_profile(user_id, org_id, bot_id)
        profile.set_fact(fact_key, value, confidence, source)
        self._save()

    # ── Conversation summary (PROMPT 5 context memory) ─────────────

    def get_conversation_summary(self, conv_id: str) -> str:
        return self._summaries.get(conv_id, "")

    def set_conversation_summary(self, conv_id: str, summary: str):
        if not conv_id or not summary:
            return
        self._summaries[conv_id] = summary
        self._save()

    # ── Persist ─────────────────────────────────────────────────

    def _save(self):
        if not self._persist_path:
            return
        try:
            profiles = {}
            for k, profile in self._long.items():
                profiles[k] = {
                    "user_id":    profile.user_id,
                    "org_id":     profile.org_id,
                    "bot_id":     profile.bot_id,
                    "total_convs": profile.total_convs,
                    "created_at": profile.created_at,
                    "updated_at": profile.updated_at,
                    "facts":      {
                        fk: asdict(fv)
                        for fk, fv in profile.facts.items()
                    },
                }
            data = {
                "profiles": profiles,
                "conversation_summaries": self._summaries,
            }
            self._persist_path.parent.mkdir(parents=True, exist_ok=True)
            self._persist_path.write_text(json.dumps(data, ensure_ascii=False, indent=2))
        except Exception as e:
            print(f"[MemoryStore] Save error: {e}")

    def _load(self):
        if not self._persist_path or not self._persist_path.exists():
            return
        try:
            data = json.loads(self._persist_path.read_text())
            # Format baru: {"profiles": {...}, "conversation_summaries": {...}}.
            # Format lama: profil langsung di root — tetap didukung untuk file lama.
            if "profiles" in data:
                profiles = data.get("profiles", {})
                self._summaries = data.get("conversation_summaries", {})
            else:
                profiles = data
            for k, d in profiles.items():
                profile = UserProfile(
                    user_id    = d["user_id"],
                    org_id     = d["org_id"],
                    bot_id     = d["bot_id"],
                    total_convs = d.get("total_convs", 0),
                    created_at = d.get("created_at", _now()),
                    updated_at = d.get("updated_at", _now()),
                )
                for fk, fv in d.get("facts", {}).items():
                    profile.facts[fk] = LongTermFact(**fv)
                self._long[k] = profile
            print(f"[MemoryStore] Loaded {len(self._long)} user profiles, {len(self._summaries)} conversation summaries")
        except Exception as e:
            print(f"[MemoryStore] Load error: {e}")

    def stats(self) -> dict:
        return {
            "active_conversations": len(self._short),
            "user_profiles":        len(self._long),
            "total_facts":          sum(len(p.facts) for p in self._long.values()),
            "conversation_summaries": len(self._summaries),
        }


# ─── MEMORY AGENT ─────────────────────────────────────────────

# Singleton store — shared across all instances
_global_store: MemoryStore | None = None

def get_memory_store(persist_path: str | None = None) -> MemoryStore:
    global _global_store
    if _global_store is None:
        _global_store = MemoryStore(persist_path=persist_path)
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
        persist_path: str | None = "data/memory.json",
    ):
        super().__init__(
            api_key=api_key,
            model=model,
            base_url=base_url,
            app_url=app_url,
        )
        self.store = get_memory_store(persist_path=persist_path)

    # ── READ: inject memori ke context ──────────────────────────

    def enrich_context(self, context: dict) -> dict:
        """
        Panggil ini SEBELUM Supervisor.process() untuk inject memori.
        Return context yang sudah diperkaya dengan memori.
        """
        conv_id = context.get("conversation_id", "")
        user_id = context.get("user_id") or context.get("metadata", {}).get("userId", "anonymous")
        org_id  = context.get("org_id", "")
        bot_id  = context.get("bot_id", "")

        enriched = dict(context)

        # 1. Short-term: tambahkan pesan user terbaru ke STM
        user_msg = context.get("user_message", "")
        if user_msg and conv_id:
            self.store.add_to_stm(conv_id, "user", user_msg)

        # 2. Long-term: inject profil user ke knowledge_base_context
        if user_id and user_id != "anonymous":
            profile = self.store.get_profile(user_id, org_id, bot_id)
            profile_ctx = profile.to_context_string()
            if profile_ctx:
                existing_kb = enriched.get("knowledge_base_context", "")
                enriched["knowledge_base_context"] = (
                    profile_ctx + "\n\n" + existing_kb
                ).strip()

        # 2.5 Ringkasan percakapan: beri kesinambungan untuk follow-up
        # (mis. "Kalau yang Pro gimana?" setelah membahas paket sebelumnya).
        if conv_id:
            summary = self.store.get_conversation_summary(conv_id)
            if summary:
                existing_kb = enriched.get("knowledge_base_context", "")
                enriched["knowledge_base_context"] = (
                    f"## Ringkasan percakapan sejauh ini\n{summary}\n\n" + existing_kb
                ).strip()

        # 3. Tandai user_id di context
        enriched["_memory_user_id"] = user_id
        return enriched

    # ── WRITE: ekstrak & simpan fakta baru ──────────────────────

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

        profile = self.store.get_profile(user_id, org_id, bot_id)
        existing_facts = "\n".join(f"- {k}: {v.value}" for k, v in profile.facts.items()) or "Belum ada."
        previous_summary = self.store.get_conversation_summary(conv_id) or "Belum ada."

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

        raw = await self._call_llm(
            [{"role": "user", "content": prompt}],
            temperature=0.1,
        )

        try:
            text = raw.strip()
            if "```" in text:
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            output = json.loads(text)
        except Exception:
            output = {"facts_to_store": [], "summary": "", "forget_keys": []}

        # Simpan fakta ke store
        stored_count = 0
        for fact in output.get("facts_to_store", []):
            if fact.get("key") and fact.get("value") is not None:
                self.store.set_fact(
                    user_id    = user_id,
                    org_id     = org_id,
                    bot_id     = bot_id,
                    fact_key   = fact["key"],
                    value      = fact["value"],
                    confidence = fact.get("confidence", 0.8),
                    source     = fact.get("source", "extracted"),
                )
                stored_count += 1

        # Hapus fakta yang diminta
        for key in output.get("forget_keys", []):
            if key in profile.facts:
                del profile.facts[key]

        # Simpan ringkasan kumulatif percakapan untuk follow-up berikutnya
        new_summary = (output.get("summary") or "").strip()
        if new_summary and conv_id:
            self.store.set_conversation_summary(conv_id, new_summary)

        # Update counter
        profile.total_convs += 1

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
