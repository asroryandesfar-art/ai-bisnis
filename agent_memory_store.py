"""
agent_memory_store.py — Agent Memory Store (AI Agent Platform).

Memory khusus untuk agent-level context (berbeda dari memory_agent.py
yang untuk end-user memory). Menyimpan:
  - project_structure: struktur proyek yang sudah dipelajari agent
  - opened_files: file yang sudah dibuka dalam session
  - terminal_history: riwayat command yang dieksekusi
  - browser_history: URL yang dikunjungi
  - recent_actions: aksi-aksi terbaru yang dilakukan agent
  - tool_usage: statistik penggunaan tool
  - user_preferences: preferensi user yang diobservasi agent

Disimpan ke tabel `agent_session_memory` (per org, per session).
In-memory cache untuk akses cepat dalam satu session.
"""
from __future__ import annotations

import json
import logging
import time
from collections import deque
from dataclasses import dataclass, field
from typing import Any

import asyncpg

logger = logging.getLogger(__name__)

_MAX_HISTORY_ITEMS = 200
_MAX_ACTIONS_ITEMS = 100


@dataclass
class AgentMemory:
    org_id: str
    session_id: str = ""
    project_structure: dict = field(default_factory=dict)
    opened_files: list[str] = field(default_factory=list)
    terminal_history: list[str] = field(default_factory=list)
    browser_history: list[str] = field(default_factory=list)
    recent_actions: list[dict] = field(default_factory=list)
    tool_usage: dict[str, int] = field(default_factory=dict)
    user_preferences: dict = field(default_factory=dict)
    context_notes: list[str] = field(default_factory=list)

    def to_summary(self, max_items: int = 10) -> str:
        """Buat ringkasan memory untuk dimasukkan ke LLM context."""
        parts = []
        if self.project_structure:
            lang = self.project_structure.get("top_extensions", {})
            parts.append(f"Proyek: {self.project_structure.get('project_path', '?')} ({list(lang.keys())[:3]})")
        if self.opened_files:
            parts.append(f"File dibuka: {', '.join(self.opened_files[-max_items:])}")
        if self.terminal_history:
            parts.append(f"Command terakhir: {', '.join(self.terminal_history[-5:])}")
        if self.browser_history:
            parts.append(f"URL terakhir: {', '.join(self.browser_history[-3:])}")
        if self.context_notes:
            parts.append(f"Catatan konteks: {'; '.join(self.context_notes[-5:])}")
        return "\n".join(parts) if parts else ""


class AgentMemoryStore:
    """
    In-memory store dengan opsional persist ke DB.

    Gunakan satu instance per session agent.
    """

    def __init__(self, pool: asyncpg.Pool, org_id: str, *, session_id: str = ""):
        self._pool = pool
        self._org_id = org_id
        self._memory = AgentMemory(org_id=org_id, session_id=session_id)

    # ─── File tracking ──────────────────────────────────────────────────────

    def record_file_opened(self, path: str) -> None:
        if path not in self._memory.opened_files:
            self._memory.opened_files.append(path)
            if len(self._memory.opened_files) > _MAX_HISTORY_ITEMS:
                self._memory.opened_files.pop(0)

    def record_file_edited(self, path: str) -> None:
        self.record_file_opened(path)  # juga masuk opened_files

    def get_opened_files(self) -> list[str]:
        return list(self._memory.opened_files)

    # ─── Terminal history ────────────────────────────────────────────────────

    def record_command(self, command: str, *, exit_code: int = 0) -> None:
        entry = command[:200]
        if exit_code != 0:
            entry = f"[exit={exit_code}] {entry}"
        self._memory.terminal_history.append(entry)
        if len(self._memory.terminal_history) > _MAX_HISTORY_ITEMS:
            self._memory.terminal_history.pop(0)

    def get_terminal_history(self, limit: int = 20) -> list[str]:
        return self._memory.terminal_history[-limit:]

    # ─── Browser history ─────────────────────────────────────────────────────

    def record_url_visited(self, url: str) -> None:
        if url and url not in self._memory.browser_history:
            self._memory.browser_history.append(url[:500])
            if len(self._memory.browser_history) > _MAX_HISTORY_ITEMS:
                self._memory.browser_history.pop(0)

    def get_browser_history(self, limit: int = 20) -> list[str]:
        return self._memory.browser_history[-limit:]

    # ─── Action log ──────────────────────────────────────────────────────────

    def record_action(self, action_type: str, target: str = "", *, success: bool = True, summary: str = "") -> None:
        action = {
            "type": action_type,
            "target": target[:200],
            "success": success,
            "summary": summary[:300],
            "ts": int(time.time()),
        }
        self._memory.recent_actions.append(action)
        if len(self._memory.recent_actions) > _MAX_ACTIONS_ITEMS:
            self._memory.recent_actions.pop(0)

        # Update tool usage stats
        self._memory.tool_usage[action_type] = self._memory.tool_usage.get(action_type, 0) + 1

    def get_recent_actions(self, limit: int = 20) -> list[dict]:
        return self._memory.recent_actions[-limit:]

    def get_tool_usage_stats(self) -> dict[str, int]:
        return dict(self._memory.tool_usage)

    # ─── Project structure ───────────────────────────────────────────────────

    def update_project_structure(self, structure: dict) -> None:
        """Simpan struktur proyek yang sudah dipelajari."""
        self._memory.project_structure = structure

    def get_project_structure(self) -> dict:
        return dict(self._memory.project_structure)

    # ─── User preferences ────────────────────────────────────────────────────

    def set_preference(self, key: str, value: Any) -> None:
        self._memory.user_preferences[key] = value

    def get_preference(self, key: str, default: Any = None) -> Any:
        return self._memory.user_preferences.get(key, default)

    # ─── Context notes ───────────────────────────────────────────────────────

    def add_note(self, note: str) -> None:
        """Tambah catatan konteks bebas."""
        self._memory.context_notes.append(note[:500])
        if len(self._memory.context_notes) > 50:
            self._memory.context_notes.pop(0)

    def get_notes(self) -> list[str]:
        return list(self._memory.context_notes)

    # ─── Summary ─────────────────────────────────────────────────────────────

    def get_summary(self) -> str:
        return self._memory.to_summary()

    def get_full_state(self) -> dict:
        m = self._memory
        return {
            "org_id": m.org_id,
            "session_id": m.session_id,
            "project_structure": m.project_structure,
            "opened_files": m.opened_files[-50:],
            "terminal_history": m.terminal_history[-50:],
            "browser_history": m.browser_history[-50:],
            "recent_actions": m.recent_actions[-30:],
            "tool_usage": m.tool_usage,
            "user_preferences": m.user_preferences,
            "context_notes": m.context_notes[-20:],
        }

    # ─── Persist ──────────────────────────────────────────────────────────────

    async def save_to_db(self) -> bool:
        """Persist full memory state ke DB (opsional, fail-open)."""
        try:
            await self._pool.execute(
                """INSERT INTO agent_session_memory
                   (org_id, session_id, memory_state, updated_at)
                   VALUES ($1, $2, $3::jsonb, NOW())
                   ON CONFLICT (org_id, session_id) DO UPDATE
                   SET memory_state = EXCLUDED.memory_state, updated_at = NOW()""",
                self._org_id, self._memory.session_id or "default",
                json.dumps(self.get_full_state()),
            )
            return True
        except Exception as e:
            logger.debug("agent_memory_store.save_to_db gagal: %s", e)
            return False

    async def load_from_db(self) -> bool:
        """Muat memory state dari DB (opsional, fail-open)."""
        try:
            row = await self._pool.fetchrow(
                """SELECT memory_state FROM agent_session_memory
                   WHERE org_id=$1 AND session_id=$2
                   ORDER BY updated_at DESC LIMIT 1""",
                self._org_id, self._memory.session_id or "default",
            )
            if not row:
                return False
            state = row["memory_state"]
            if isinstance(state, str):
                state = json.loads(state)
            m = self._memory
            m.project_structure = state.get("project_structure", {})
            m.opened_files = state.get("opened_files", [])
            m.terminal_history = state.get("terminal_history", [])
            m.browser_history = state.get("browser_history", [])
            m.recent_actions = state.get("recent_actions", [])
            m.tool_usage = state.get("tool_usage", {})
            m.user_preferences = state.get("user_preferences", {})
            m.context_notes = state.get("context_notes", [])
            return True
        except Exception as e:
            logger.debug("agent_memory_store.load_from_db gagal: %s", e)
            return False


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS agent_session_memory (
    id            UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    org_id        UUID NOT NULL,
    session_id    TEXT NOT NULL DEFAULT 'default',
    memory_state  JSONB NOT NULL DEFAULT '{}',
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (org_id, session_id)
);
CREATE INDEX IF NOT EXISTS idx_agent_session_memory_org
    ON agent_session_memory(org_id, updated_at DESC);
"""


async def ensure_schema(pool: asyncpg.Pool) -> None:
    try:
        await pool.execute(SCHEMA_SQL)
    except Exception as e:
        logger.warning("agent_memory_store.ensure_schema: %s", e)
