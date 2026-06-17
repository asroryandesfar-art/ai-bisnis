"""
Knowledge URL Seeder — BotNesia

Modul ini mengelola:
- Bulk import URL ke knowledge_sources queue
- URL normalization dan duplicate check
- Background crawler (memanfaatkan _fetch_website_text + _process_document_sync dari main)
- Status tracking per-source (pending → crawling → indexed / failed)
- Retry untuk source yang gagal
- Seed loader dari JSON files di seeds/
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import os
import re
import uuid
from pathlib import Path
from typing import Any
from urllib.parse import urlparse, urlunparse

logger = logging.getLogger(__name__)

SEEDS_DIR = Path(__file__).parent / "seeds"
MARKETPLACE_SEED_FILE = Path(__file__).parent / "backend" / "seeds" / "agent_marketplace_1000_urls.json"

# Concurrency limit saat crawl (jangan spam website)
_CRAWL_SEMAPHORE_SIZE = 3
_MAX_RETRY = 3
_CRAWL_DELAY_S = 1.5  # jeda antar request dalam satu batch

VALID_STATUSES = ("pending", "crawling", "indexed", "failed", "skipped")
VALID_PRIORITIES = ("high", "normal", "low")


# ── URL utilities ────────────────────────────────────────────────────────────

def normalize_url(url: str) -> str:
    """Normalisasi URL: lowercase scheme+host, hapus fragment, strip trailing slash."""
    url = (url or "").strip()
    if not url:
        return ""
    try:
        p = urlparse(url)
        scheme = (p.scheme or "https").lower()
        netloc = (p.netloc or "").lower()
        path = p.path.rstrip("/") or "/"
        query = p.query
        return urlunparse((scheme, netloc, path, "", query, ""))
    except Exception:
        return url.strip()


def url_fingerprint(url: str) -> str:
    """SHA-256 fingerprint dari normalized URL untuk dedup cepat."""
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()


def is_valid_url(url: str) -> bool:
    try:
        p = urlparse(url)
        return p.scheme in ("http", "https") and bool(p.netloc)
    except Exception:
        return False


def _title_from_url(url: str) -> str:
    try:
        p = urlparse(url)
        parts = [x for x in p.path.split("/") if x]
        slug = parts[-1] if parts else p.netloc
        return slug.replace("-", " ").replace("_", " ").title()
    except Exception:
        return url[:80]


# ── Seed file loader ─────────────────────────────────────────────────────────

def load_marketplace_seed_file(path: str | os.PathLike | None = None) -> list[dict]:
    """Load Phase 4 marketplace URL seed file."""
    seed_path = Path(path) if path else MARKETPLACE_SEED_FILE
    try:
        data = json.loads(seed_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        logger.warning("Marketplace seed file tidak ditemukan: %s", seed_path)
        return []
    except Exception as exc:
        logger.error("Gagal load marketplace seed file %s: %s", seed_path, exc)
        return []
    return data if isinstance(data, list) else []


async def _installed_marketplace_bot_map(pool, *, org_id: str) -> dict[str, str]:
    rows = await pool.fetch(
        """SELECT mt.key, ti.bot_id
             FROM tenant_template_installs ti
             JOIN marketplace_templates mt ON mt.id = ti.template_id
             JOIN bots b ON b.id = ti.bot_id
            WHERE ti.org_id=$1 AND b.status <> 'inactive'""",
        org_id,
    )
    return {str(row["key"]): str(row["bot_id"]) for row in rows}


async def bulk_import_marketplace_seed(
    pool,
    *,
    org_id: str,
    fallback_bot_id: str | None = None,
    seed_path: str | os.PathLike | None = None,
    installed_only: bool = False,
) -> dict:
    """Queue marketplace seed URLs without crawling everything at once.

    Installed marketplace agents are mapped to their own bot_id. If a template is
    not installed, fallback_bot_id can be used for preview/import while agent_type
    still isolates the source metadata.
    """
    rows = load_marketplace_seed_file(seed_path)
    installed = await _installed_marketplace_bot_map(pool, org_id=org_id)
    imported = skipped_duplicate = skipped_invalid = skipped_uninstalled = 0
    per_agent: dict[str, int] = {}
    per_category: dict[str, int] = {}
    touched_bots: set[str] = set()

    for entry in rows:
        agent_id = str(entry.get("agent_id") or entry.get("agent") or "").strip()
        target_bot_id = installed.get(agent_id) or fallback_bot_id
        if not target_bot_id or (installed_only and agent_id not in installed):
            skipped_uninstalled += 1
            continue
        url = (entry.get("url") or "").strip()
        if not url or not is_valid_url(url):
            skipped_invalid += 1
            continue
        _, created = await get_or_create_knowledge_source(
            pool,
            org_id=org_id,
            bot_id=str(target_bot_id),
            url=url,
            title=entry.get("agent_name") or entry.get("title"),
            category=entry.get("category"),
            agent_type=agent_id,
            priority=entry.get("priority", "normal"),
            language=entry.get("language", "id"),
            trusted=bool(entry.get("trusted", True)),
        )
        if created:
            imported += 1
            per_agent[agent_id] = per_agent.get(agent_id, 0) + 1
            category = str(entry.get("category") or "uncategorized")
            per_category[category] = per_category.get(category, 0) + 1
            touched_bots.add(str(target_bot_id))
        else:
            skipped_duplicate += 1

    return {
        "imported": imported,
        "skipped_duplicate": skipped_duplicate,
        "skipped_invalid": skipped_invalid,
        "skipped_uninstalled": skipped_uninstalled,
        "total": len(rows),
        "agent_count": len({str(row.get("agent_id")) for row in rows if row.get("agent_id")}),
        "per_agent": per_agent,
        "per_category": per_category,
        "touched_bots": sorted(touched_bots),
    }


async def get_marketplace_seed_status(
    pool,
    *,
    org_id: str,
    bot_id: str | None = None,
    agent_id: str | None = None,
    category: str | None = None,
    search: str | None = None,
) -> dict:
    conditions = ["org_id=$1"]
    params: list[Any] = [org_id]
    if bot_id:
        params.append(bot_id)
        conditions.append(f"bot_id=${len(params)}")
    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_type=${len(params)}")
    if category:
        params.append(category)
        conditions.append(f"category=${len(params)}")
    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_type=${len(params)}")
    if search:
        params.append(f"%{search.lower()}%")
        conditions.append(f"(LOWER(url) LIKE ${len(params)} OR LOWER(title) LIKE ${len(params)})")
    where = " AND ".join(conditions)
    status_rows = await pool.fetch(
        f"""SELECT status, COUNT(*)::int AS count
              FROM knowledge_sources
             WHERE {where}
             GROUP BY status""",
        *params,
    )
    agent_rows = await pool.fetch(
        f"""SELECT COALESCE(agent_type,'unknown') AS agent_id, COUNT(*)::int AS total,
                   COUNT(*) FILTER (WHERE status='pending')::int AS pending,
                   COUNT(*) FILTER (WHERE status='crawling')::int AS crawling,
                   COUNT(*) FILTER (WHERE status='indexed')::int AS indexed,
                   COUNT(*) FILTER (WHERE status='failed')::int AS failed
              FROM knowledge_sources
             WHERE {where}
             GROUP BY COALESCE(agent_type,'unknown')
             ORDER BY total DESC, agent_id""",
        *params,
    )
    category_rows = await pool.fetch(
        f"""SELECT COALESCE(category,'uncategorized') AS category, COUNT(*)::int AS total
              FROM knowledge_sources
             WHERE {where}
             GROUP BY COALESCE(category,'uncategorized')
             ORDER BY total DESC, category""",
        *params,
    )
    stats = {s: 0 for s in VALID_STATUSES}
    total = 0
    for row in status_rows:
        stats[row["status"]] = row["count"]
        total += row["count"]
    stats["total"] = total
    return {
        "stats": stats,
        "per_agent": [dict(row) for row in agent_rows],
        "per_category": [dict(row) for row in category_rows],
    }


async def retry_failed_sources(
    pool,
    *,
    org_id: str,
    bot_id: str | None = None,
    agent_id: str | None = None,
    category: str | None = None,
) -> int:
    conditions = ["org_id=$1", "status='failed'", f"retry_count < {_MAX_RETRY}"]
    params: list[Any] = [org_id]
    if bot_id:
        params.append(bot_id)
        conditions.append(f"bot_id=${len(params)}")
    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_type=${len(params)}")
    if category:
        params.append(category)
        conditions.append(f"category=${len(params)}")
    where = " AND ".join(conditions)
    result = await pool.execute(f"UPDATE knowledge_sources SET status='pending', error_message=NULL, retry_count=retry_count+1 WHERE {where}", *params)
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


def load_seed_file(agent_type: str) -> list[dict]:
    """Load URL list dari seeds/<agent_type>_urls.json."""
    filename = f"{agent_type}_urls.json"
    path = SEEDS_DIR / filename
    if not path.exists():
        logger.warning("Seed file tidak ditemukan: %s", path)
        return []
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            logger.warning("Seed file %s bukan list JSON", filename)
            return []
        return data
    except Exception as e:
        logger.error("Gagal load seed file %s: %s", filename, e)
        return []


def list_available_seeds() -> list[str]:
    """Daftar agent_type yang punya seed file."""
    if not SEEDS_DIR.exists():
        return []
    return [
        p.stem.replace("_urls", "")
        for p in SEEDS_DIR.glob("*_urls.json")
    ]


# ── Database helpers ─────────────────────────────────────────────────────────

async def get_or_create_knowledge_source(
    pool,
    *,
    org_id: str,
    bot_id: str,
    url: str,
    title: str | None = None,
    category: str | None = None,
    agent_type: str | None = None,
    priority: str = "normal",
    language: str = "id",
    trusted: bool = False,
) -> tuple[str, bool]:
    """
    Insert sumber URL baru. Return (source_id, created).
    Jika URL sudah ada untuk bot ini → return existing id, created=False.
    """
    norm = normalize_url(url)
    existing = await pool.fetchval(
        "SELECT id FROM knowledge_sources WHERE bot_id=$1 AND url=$2",
        bot_id, norm,
    )
    if existing:
        return str(existing), False

    source_id = str(uuid.uuid4())
    await pool.execute(
        """INSERT INTO knowledge_sources
           (id, org_id, bot_id, tenant_id, agent_id, url, title, category, agent_type,
            priority, language, trusted, status)
           VALUES ($1,$2,$3,$2,$3,$4,$5,$6,$7,$8,$9,$10,'pending')""",
        source_id, org_id, bot_id, norm,
        title or _title_from_url(norm),
        category, agent_type,
        priority if priority in VALID_PRIORITIES else "normal",
        language, trusted,
    )
    return source_id, True


async def bulk_import_urls(
    pool,
    *,
    org_id: str,
    bot_id: str,
    urls_data: list[dict],
) -> dict:
    """
    Bulk import list URL ke knowledge_sources.
    Setiap entry: {url, title?, category?, priority?, language?, trusted?}
    Return: {imported, skipped_duplicate, skipped_invalid, total}
    """
    imported = 0
    skipped_duplicate = 0
    skipped_invalid = 0

    for entry in urls_data:
        url = (entry.get("url") or "").strip()
        if not url or not is_valid_url(url):
            skipped_invalid += 1
            continue
        _, created = await get_or_create_knowledge_source(
            pool,
            org_id=org_id,
            bot_id=bot_id,
            url=url,
            title=entry.get("title"),
            category=entry.get("category"),
            agent_type=entry.get("agent"),
            priority=entry.get("priority", "normal"),
            language=entry.get("language", "id"),
            trusted=bool(entry.get("trusted", False)),
        )
        if created:
            imported += 1
        else:
            skipped_duplicate += 1

    return {
        "imported": imported,
        "skipped_duplicate": skipped_duplicate,
        "skipped_invalid": skipped_invalid,
        "total": len(urls_data),
    }


async def seed_agent_urls(
    pool,
    *,
    org_id: str,
    bot_id: str,
    agent_type: str,
) -> dict:
    """Load seed file dan bulk import ke bot."""
    urls_data = load_seed_file(agent_type)
    if not urls_data:
        return {"error": f"Seed file untuk '{agent_type}' tidak ditemukan atau kosong", "imported": 0}
    result = await bulk_import_urls(pool, org_id=org_id, bot_id=bot_id, urls_data=urls_data)
    result["agent_type"] = agent_type
    result["seed_count"] = len(urls_data)
    return result


async def get_sources(
    pool,
    *,
    org_id: str,
    bot_id: str | None = None,
    status: str | None = None,
    category: str | None = None,
    agent_id: str | None = None,
    search: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[dict]:
    """List knowledge_sources dengan filter opsional."""
    conditions = ["org_id=$1"]
    params: list[Any] = [org_id]

    if bot_id:
        params.append(bot_id)
        conditions.append(f"bot_id=${len(params)}")
    if status:
        params.append(status)
        conditions.append(f"status=${len(params)}")
    if category:
        params.append(category)
        conditions.append(f"category=${len(params)}")
    if agent_id:
        params.append(agent_id)
        conditions.append(f"agent_type=${len(params)}")
    if search:
        params.append(f"%{search.lower()}%")
        conditions.append(f"(LOWER(url) LIKE ${len(params)} OR LOWER(title) LIKE ${len(params)})")

    where = " AND ".join(conditions)
    params.extend([limit, offset])
    rows = await pool.fetch(
        f"""SELECT id, org_id, bot_id, url, title, category, agent_type,
                   priority, language, trusted, status, error_message,
                   retry_count, document_id, last_crawled_at, created_at
            FROM knowledge_sources
            WHERE {where}
            ORDER BY
              CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END,
              created_at DESC
            LIMIT ${len(params)-1} OFFSET ${len(params)}""",
        *params,
    )
    return [dict(r) for r in rows]


async def get_source_stats(pool, *, org_id: str, bot_id: str | None = None) -> dict:
    """Statistik status sources untuk satu org / bot."""
    cond = "org_id=$1"
    params: list[Any] = [org_id]
    if bot_id:
        params.append(bot_id)
        cond += f" AND bot_id=${len(params)}"

    rows = await pool.fetch(
        f"SELECT status, COUNT(*) AS cnt FROM knowledge_sources WHERE {cond} GROUP BY status",
        *params,
    )
    stats = {s: 0 for s in VALID_STATUSES}
    total = 0
    for r in rows:
        s = r["status"]
        if s in stats:
            stats[s] = r["cnt"]
        total += r["cnt"]
    stats["total"] = total
    return stats


async def retry_source(pool, *, source_id: str, org_id: str) -> bool:
    """Reset source yang failed ke pending untuk dicrawl ulang."""
    result = await pool.execute(
        """UPDATE knowledge_sources
           SET status='pending', error_message=NULL, retry_count=retry_count+1
           WHERE id=$1 AND org_id=$2 AND status='failed' AND retry_count < $3""",
        source_id, org_id, _MAX_RETRY,
    )
    return result != "UPDATE 0"


async def retry_all_failed(pool, *, org_id: str, bot_id: str) -> int:
    """Retry semua source failed yang belum melebihi max retry."""
    result = await pool.execute(
        """UPDATE knowledge_sources
           SET status='pending', error_message=NULL
           WHERE org_id=$1 AND bot_id=$2 AND status='failed' AND retry_count < $3""",
        org_id, bot_id, _MAX_RETRY,
    )
    try:
        return int(result.split()[-1])
    except Exception:
        return 0


async def delete_source(pool, *, source_id: str, org_id: str) -> bool:
    result = await pool.execute(
        "DELETE FROM knowledge_sources WHERE id=$1 AND org_id=$2",
        source_id, org_id,
    )
    return result != "DELETE 0"


# ── Background Crawler ───────────────────────────────────────────────────────

async def crawl_one_source(pool, source: dict, fetch_fn, process_fn) -> None:
    """
    Crawl satu URL source:
    1. Set status=crawling
    2. Insert ke documents (reuse existing table + logic)
    3. Panggil process_fn (= _process_document_sync dari main.py)
    4. Update status=indexed / failed
    """
    source_id = str(source["id"])
    org_id = str(source["org_id"])
    bot_id = str(source["bot_id"])
    url = source["url"]
    title = source.get("title") or _title_from_url(url)

    await pool.execute(
        "UPDATE knowledge_sources SET status='crawling', last_crawled_at=NOW() WHERE id=$1",
        source_id,
    )

    doc_id = None
    try:
        # Cek apakah dokumen dengan URL ini sudah ada di bot
        existing_doc = await pool.fetchval(
            "SELECT id FROM documents WHERE bot_id=$1 AND source_url=$2",
            bot_id, url,
        )
        if existing_doc:
            doc_id = str(existing_doc)
        else:
            doc_id = str(uuid.uuid4())
            await pool.execute(
                """INSERT INTO documents
                   (id, org_id, bot_id, filename, file_size, mime_type, status, source_type, source_url)
                   VALUES ($1,$2,$3,$4,$5,$6,'pending','url',$7)""",
                doc_id, org_id, bot_id,
                title, 0, "text/html", url,
            )
            # Panggil processor (fungsi yang di-inject dari main.py)
            await process_fn(pool, doc_id, source_type="url", source_url=url)

        doc_status = await pool.fetchval("SELECT status FROM documents WHERE id=$1", doc_id)
        if doc_status == "ready":
            await pool.execute(
                """UPDATE knowledge_sources
                   SET status='indexed', document_id=$1, error_message=NULL
                   WHERE id=$2""",
                doc_id, source_id,
            )
            rows = await pool.fetch(
                """SELECT c.id, c.content, c.chunk_index, e.embedding
                   FROM doc_chunks c
                   LEFT JOIN doc_chunk_embeddings e ON e.chunk_id = c.id
                   WHERE c.document_id=$1
                   ORDER BY c.chunk_index""",
                doc_id,
            )
            for row in rows:
                await pool.execute(
                    """INSERT INTO knowledge_chunks
                       (id, org_id, bot_id, tenant_id, agent_id, source_id, content, embedding, metadata)
                       VALUES ($1,$2,$3,$2,$3,$4,$5,$6,$7::jsonb)
                       ON CONFLICT (id) DO UPDATE SET
                         source_id=EXCLUDED.source_id, content=EXCLUDED.content,
                         embedding=EXCLUDED.embedding, metadata=EXCLUDED.metadata""",
                    str(row["id"]), org_id, bot_id, source_id, row["content"], row["embedding"],
                    json.dumps({"document_id": doc_id, "chunk_index": row["chunk_index"], "url": url}),
                )
        else:
            err = await pool.fetchval("SELECT error_msg FROM documents WHERE id=$1", doc_id) or "Dokumen tidak siap"
            raise ValueError(err)

    except Exception as e:
        err_msg = str(e)[:500]
        logger.warning("Crawl gagal source=%s url=%s: %s", source_id, url, err_msg)
        await pool.execute(
            """UPDATE knowledge_sources
               SET status='failed', error_message=$1
               WHERE id=$2""",
            err_msg, source_id,
        )


async def run_crawler_batch(
    pool,
    *,
    org_id: str,
    bot_id: str,
    fetch_fn,
    process_fn,
    batch_size: int = 10,
) -> dict:
    """
    Ambil batch source pending, crawl dengan concurrency terbatas.
    fetch_fn: _fetch_website_text dari main.py
    process_fn: _process_document_sync dari main.py
    """
    rows = await pool.fetch(
        """SELECT id, org_id, bot_id, url, title
           FROM knowledge_sources
           WHERE org_id=$1 AND bot_id=$2 AND status='pending'
           ORDER BY CASE priority WHEN 'high' THEN 0 WHEN 'normal' THEN 1 ELSE 2 END, created_at
           LIMIT $3""",
        org_id, bot_id, batch_size,
    )

    if not rows:
        return {"crawled": 0, "message": "Tidak ada URL pending"}

    sem = asyncio.Semaphore(_CRAWL_SEMAPHORE_SIZE)

    async def _crawl_with_limit(source):
        async with sem:
            await crawl_one_source(pool, dict(source), fetch_fn, process_fn)
            await asyncio.sleep(_CRAWL_DELAY_S)

    tasks = [_crawl_with_limit(r) for r in rows]
    results = await asyncio.gather(*tasks, return_exceptions=True)

    errors = sum(1 for r in results if isinstance(r, Exception))
    return {
        "crawled": len(rows),
        "errors": errors,
        "success": len(rows) - errors,
    }
