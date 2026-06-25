"""
agents/marketing_agent.py — Marketing Agent (AI Workforce Phase 2)

Generate konten marketing (Instagram, TikTok, Facebook, Blog, Email,
WhatsApp), kelola content calendar, dan catat engagement/konversi --
untuk bisnis TENANT sendiri (bukan marketing BotNesia sendiri).

KETERBATASAN JUJUR (Truthfulness Policy, lihat tool_registry.py): codebase
ini TIDAK punya kredensial publish API Instagram/TikTok/Facebook Content
Publishing -- AI hanya menyiapkan & menjadwalkan draft, publikasi
sungguhan ke platform tetap dilakukan MANUAL oleh tenant. Engagement/
konversi juga dicatat manual (tenant input angka dari Insights platform
masing-masing), tidak ada auto-fetch.

Semua fungsi di bawah dipakai bersama oleh:
  - bn_platform/marketing.py (router dashboard Marketing Center, RBAC-gated)
  - MarketingAgent.run() (generate konten dari brief bahasa natural, hanya
    dipanggil dari endpoint terautentikasi -- bukan dari chat publik).
"""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import asyncpg

from base import BaseAgent, AgentResult

PLATFORMS = {"instagram", "tiktok", "facebook", "blog", "email", "whatsapp"}
CONTENT_STATUSES = {"draft", "scheduled", "ready_to_publish", "published", "cancelled"}
METRIC_TYPES = {"likes", "comments", "shares", "views", "clicks", "conversions"}
CAMPAIGN_STATUSES = {"draft", "active", "completed", "cancelled"}

_PLATFORM_STYLE = {
    "instagram": "Caption Instagram: hook kuat di kalimat pertama, nada santai, tutup dengan call-to-action, sertakan 5-10 hashtag relevan.",
    "tiktok": "Skrip/hook TikTok: 1-2 kalimat hook untuk 3 detik pertama, lalu poin-poin singkat untuk voice over, nada energik.",
    "facebook": "Post Facebook: paragraf singkat informatif, nada hangat, cocok untuk audiens lebih luas/dewasa, sertakan call-to-action.",
    "blog": "Artikel blog: judul menarik + body terstruktur (pembuka, 2-3 poin utama, penutup dengan CTA), nada informatif.",
    "email": "Email campaign: subject line menarik (di awal body sebagai 'Subject: ...'), body personal, CTA jelas.",
    "whatsapp": "Broadcast WhatsApp: pesan singkat, personal, langsung ke inti tawaran, CTA jelas, tanpa hashtag.",
}


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ─── CAMPAIGNS ──────────────────────────────────────────────────

async def create_campaign(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None,
                           name: str, goal: str | None, target_audience: str | None,
                           start_date: datetime | None, end_date: datetime | None,
                           created_by: str | None) -> dict:
    campaign_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO marketing_campaigns
               (id, org_id, bot_id, name, goal, target_audience, start_date, end_date, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9) RETURNING *""",
        campaign_id, org_id, bot_id, name, goal, target_audience, start_date, end_date,
        str(created_by) if created_by else None,
    )
    return dict(row)


async def update_campaign_status(pool: asyncpg.Pool, *, org_id: str, campaign_id: str,
                                  status: str) -> dict | None:
    if status not in CAMPAIGN_STATUSES:
        raise ValueError(f"status tidak valid: {status}")
    row = await pool.fetchrow(
        """UPDATE marketing_campaigns SET status=$1, updated_at=NOW()
           WHERE id=$2 AND org_id=$3 RETURNING *""",
        status, campaign_id, org_id,
    )
    return dict(row) if row else None


# ─── CONTENT ────────────────────────────────────────────────────

def _jsonb(value, default=None):
    if isinstance(value, str):
        try:
            return json.loads(value)
        except Exception:
            return default if default is not None else []
    if value is None:
        return default if default is not None else []
    return value


def _content_out(row: dict) -> dict:
    out = dict(row)
    out["hashtags"] = _jsonb(out.get("hashtags"))
    return out


async def create_content(pool: asyncpg.Pool, *, org_id: str, bot_id: str | None,
                          campaign_id: str | None, platform: str, title: str | None,
                          body: str, hashtags: list[str] | None, created_by: str | None) -> dict:
    if platform not in PLATFORMS:
        raise ValueError(f"platform tidak valid: {platform}")
    content_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO marketing_content
               (id, org_id, campaign_id, bot_id, platform, title, body, hashtags, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7,$8::jsonb,$9) RETURNING *""",
        content_id, org_id, campaign_id, bot_id, platform, title, body,
        json.dumps(hashtags or []), str(created_by) if created_by else None,
    )
    return _content_out(dict(row))


async def schedule_content(pool: asyncpg.Pool, *, org_id: str, content_id: str,
                            scheduled_at: datetime) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE marketing_content SET status='scheduled', scheduled_at=$1, updated_at=NOW()
           WHERE id=$2 AND org_id=$3 RETURNING *""",
        scheduled_at, content_id, org_id,
    )
    return _content_out(dict(row)) if row else None


async def approve_content(pool: asyncpg.Pool, *, org_id: str, content_id: str,
                           approver_id: str | None) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE marketing_content SET status='ready_to_publish', approved_by=$1, approved_at=NOW(), updated_at=NOW()
           WHERE id=$2 AND org_id=$3 RETURNING *""",
        str(approver_id) if approver_id else None, content_id, org_id,
    )
    return _content_out(dict(row)) if row else None


async def mark_content_published(pool: asyncpg.Pool, *, org_id: str, content_id: str) -> dict | None:
    """Tenant menandai sudah dipublikasikan SECARA MANUAL ke platform asli --
    tidak ada publish API otomatis di sini (lihat docstring modul)."""
    row = await pool.fetchrow(
        """UPDATE marketing_content SET status='published', published_at=NOW(), updated_at=NOW()
           WHERE id=$1 AND org_id=$2 RETURNING *""",
        content_id, org_id,
    )
    return _content_out(dict(row)) if row else None


async def cancel_content(pool: asyncpg.Pool, *, org_id: str, content_id: str) -> dict | None:
    row = await pool.fetchrow(
        """UPDATE marketing_content SET status='cancelled', updated_at=NOW()
           WHERE id=$1 AND org_id=$2 RETURNING *""",
        content_id, org_id,
    )
    return _content_out(dict(row)) if row else None


async def list_content_calendar(pool: asyncpg.Pool, org_id: str,
                                 start: datetime, end: datetime) -> list[dict]:
    rows = await pool.fetch(
        """SELECT * FROM marketing_content
           WHERE org_id=$1 AND scheduled_at IS NOT NULL
             AND scheduled_at >= $2 AND scheduled_at < $3
           ORDER BY scheduled_at ASC""",
        org_id, start, end,
    )
    return [_content_out(dict(r)) for r in rows]


async def list_due_content(pool: asyncpg.Pool, org_id: str) -> list[dict]:
    """Konten yang sudah waktunya tayang (scheduled_at terlewati, status masih
    'scheduled') -- "Auto Scheduling" di sini berarti AI menandai due, tenant
    yang mempublikasikan secara manual ke platform aslinya."""
    rows = await pool.fetch(
        """SELECT * FROM marketing_content
           WHERE org_id=$1 AND status='scheduled' AND scheduled_at <= NOW()
           ORDER BY scheduled_at ASC""",
        org_id,
    )
    return [_content_out(dict(r)) for r in rows]


# ─── ENGAGEMENT & ANALYTICS ─────────────────────────────────────

async def record_engagement(pool: asyncpg.Pool, *, org_id: str, content_id: str,
                             metric_type: str, value: int, recorded_at: datetime | None,
                             created_by: str | None) -> dict:
    if metric_type not in METRIC_TYPES:
        raise ValueError(f"metric_type tidak valid: {metric_type}")
    engagement_id = str(uuid.uuid4())
    row = await pool.fetchrow(
        """INSERT INTO marketing_engagement
               (id, org_id, content_id, metric_type, value, recorded_at, created_by)
           VALUES ($1,$2,$3,$4,$5,$6,$7) RETURNING *""",
        engagement_id, org_id, content_id, metric_type, value,
        recorded_at or _now(), str(created_by) if created_by else None,
    )
    return dict(row)


async def campaign_analytics(pool: asyncpg.Pool, org_id: str, campaign_id: str) -> dict:
    content_summary = await pool.fetch(
        """SELECT platform, status, COUNT(*) AS cnt FROM marketing_content
           WHERE org_id=$1 AND campaign_id=$2 GROUP BY platform, status""",
        org_id, campaign_id,
    )
    engagement_summary = await pool.fetch(
        """SELECT me.metric_type, COALESCE(SUM(me.value), 0) AS total
           FROM marketing_engagement me
           JOIN marketing_content mc ON mc.id = me.content_id
           WHERE mc.org_id=$1 AND mc.campaign_id=$2
           GROUP BY me.metric_type""",
        org_id, campaign_id,
    )
    return {
        "content_by_platform_status": [dict(r) for r in content_summary],
        "engagement_totals": {r["metric_type"]: int(r["total"]) for r in engagement_summary},
    }


async def dashboard_summary(pool: asyncpg.Pool, org_id: str) -> dict:
    content_counts = await pool.fetchrow(
        """SELECT
             COUNT(*) FILTER (WHERE status='draft') AS draft_cnt,
             COUNT(*) FILTER (WHERE status='scheduled') AS scheduled_cnt,
             COUNT(*) FILTER (WHERE status='ready_to_publish') AS ready_cnt,
             COUNT(*) FILTER (WHERE status='published') AS published_cnt
           FROM marketing_content WHERE org_id=$1""",
        org_id,
    )
    active_campaigns = await pool.fetchval(
        "SELECT COUNT(*) FROM marketing_campaigns WHERE org_id=$1 AND status='active'", org_id,
    )
    due_count = await pool.fetchval(
        "SELECT COUNT(*) FROM marketing_content WHERE org_id=$1 AND status='scheduled' AND scheduled_at <= NOW()",
        org_id,
    )
    engagement_30d = await pool.fetch(
        """SELECT me.metric_type, COALESCE(SUM(me.value), 0) AS total
           FROM marketing_engagement me
           WHERE me.org_id=$1 AND me.recorded_at >= NOW() - INTERVAL '30 days'
           GROUP BY me.metric_type""",
        org_id,
    )
    return {
        "active_campaigns": int(active_campaigns or 0),
        "content_draft": int(content_counts["draft_cnt"]),
        "content_scheduled": int(content_counts["scheduled_cnt"]),
        "content_ready_to_publish": int(content_counts["ready_cnt"]),
        "content_published": int(content_counts["published_cnt"]),
        "content_due_now": int(due_count or 0),
        "engagement_30d": {r["metric_type"]: int(r["total"]) for r in engagement_30d},
    }


# ─── AGENT ──────────────────────────────────────────────────────

class MarketingAgent(BaseAgent):
    name = "marketing_agent"
    skills = ["campaign_management", "content_drafting", "content_scheduling", "engagement_analytics"]
    tools: list[str] = [
        "channel_messaging", "knowledge_search", "web_search", "browser_open", "memory_lookup",
        "news_search", "document_generator",
    ]
    goals = [
        "Membuat draft konten marketing sesuai gaya platform yang diminta.",
        "Mengelola kampanye dan kalender konten tenant serta menganalisis engagement.",
    ]
    system_prompt = """Kamu adalah Marketing Agent dalam sistem multi-agent BotNesia (AI Workforce).

Tugas: generate draft konten marketing dari brief singkat staf tenant
(Bahasa Indonesia), untuk salah satu platform: instagram, tiktok, facebook,
blog, email, whatsapp. Ikuti gaya platform yang diminta.

Balas HANYA JSON dengan field: title (boleh null untuk platform tanpa
judul seperti instagram/whatsapp), body (isi konten lengkap sesuai gaya
platform), hashtags (list string, [] jika tidak relevan untuk platform
tersebut). Jangan menyertakan penjelasan di luar JSON."""

    async def generate_content(self, *, platform: str, brief: str) -> dict:
        style = _PLATFORM_STYLE.get(platform, "")
        messages = [
            {"role": "system", "content": self.system_prompt + f"\n\nGaya platform '{platform}': {style}\n\nOutput harus JSON."},
            {"role": "user", "content": brief},
        ]
        return await self._call_llm_json(
            messages, temperature=0.6,
            default={"title": None, "body": "", "hashtags": [], "_llm_unavailable": True},
        )

    async def run(self, context: dict) -> AgentResult:
        """Hanya dipanggil dari permukaan TERAUTENTIKASI (lihat docstring modul).
        context wajib: user_message (brief), platform, org_id, pool, actor_user_id.
        campaign_id/bot_id opsional."""
        brief = context.get("user_message", "") or ""
        platform = context.get("platform")
        org_id = context.get("org_id")
        pool: asyncpg.Pool | None = context.get("pool") or context.get("_observability_pool")
        actor_user_id = context.get("actor_user_id")
        bot_id = context.get("bot_id")
        campaign_id = context.get("campaign_id")

        if not org_id or not pool:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                                error="org_id dan pool wajib diisi")
        if platform not in PLATFORMS:
            return AgentResult(agent=self.name, success=False, output={}, latency_ms=0,
                                error=f"platform tidak valid: {platform}")

        generated = await self.generate_content(platform=platform, brief=brief)
        if generated.get("_llm_unavailable") or not generated.get("body"):
            return AgentResult(agent=self.name, success=False, output={"generated": generated},
                                latency_ms=0, error="Gagal generate konten (LLM tidak tersedia)")

        try:
            content = await create_content(
                pool, org_id=org_id, bot_id=bot_id, campaign_id=campaign_id, platform=platform,
                title=generated.get("title"), body=generated["body"],
                hashtags=generated.get("hashtags") or [], created_by=actor_user_id,
            )
        except Exception as exc:
            return AgentResult(agent=self.name, success=False, output={"generated": generated},
                                latency_ms=0, error=str(exc))

        try:
            from memory_agent import get_memory_store
            store = get_memory_store()
            await store.apply_fact_updates(
                user_id=str(actor_user_id) if actor_user_id else "unknown",
                org_id=str(org_id), bot_id=str(bot_id) if bot_id else "_marketing_agent",
                facts_to_store=[{
                    "key": "last_marketing_content", "value": {"platform": platform, "at": _now().isoformat()},
                    "confidence": 1.0, "source": "explicit",
                }],
                forget_keys=[], pool=pool,
            )
        except Exception:
            pass

        return AgentResult(agent=self.name, success=True, output={"content": content}, latency_ms=0)
