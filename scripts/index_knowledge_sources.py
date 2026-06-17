#!/usr/bin/env python3
"""Batch index queued BotNesia knowledge sources.

This intentionally processes only limited batches per run. Schedule it via cron,
systemd timer, Railway cron, or a worker queue instead of crawling everything at
once.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import asyncpg  # noqa: E402
import knowledge_seeder  # noqa: E402


async def _index(args) -> dict:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise SystemExit("DATABASE_URL wajib diset")
    # Import main lazily because it loads app settings and processing callbacks.
    from main import _fetch_website_text, _process_document_sync

    pool = await asyncpg.create_pool(dsn)
    summary = {"batches": 0, "crawled": 0, "errors": 0, "groups": []}
    try:
        group_params = []
        where = ["status='pending'"]
        if args.tenant_id:
            group_params.append(args.tenant_id)
            where.append(f"org_id=${len(group_params)}")
        if args.bot_id:
            group_params.append(args.bot_id)
            where.append(f"bot_id=${len(group_params)}")
        group_params.append(max(1, args.max_groups))
        rows = await pool.fetch(
            f"""SELECT org_id, bot_id, COUNT(*)::int AS pending
                  FROM knowledge_sources
                 WHERE {' AND '.join(where)}
                 GROUP BY org_id, bot_id
                 ORDER BY pending DESC
                 LIMIT ${len(group_params)}""",
            *group_params,
        )
        for row in rows:
            if summary["batches"] >= args.max_batches:
                break
            result = await knowledge_seeder.run_crawler_batch(
                pool,
                org_id=str(row["org_id"]),
                bot_id=str(row["bot_id"]),
                fetch_fn=_fetch_website_text,
                process_fn=_process_document_sync,
                batch_size=args.batch_size,
            )
            summary["batches"] += 1
            summary["crawled"] += int(result.get("crawled", 0))
            summary["errors"] += int(result.get("errors", 0))
            summary["groups"].append({"org_id": str(row["org_id"]), "bot_id": str(row["bot_id"]), **result})
            if args.delay:
                await asyncio.sleep(args.delay)
        return summary
    finally:
        await pool.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--batch-size", type=int, default=20)
    parser.add_argument("--delay", type=float, default=2.0)
    parser.add_argument("--max-batches", type=int, default=1)
    parser.add_argument("--max-groups", type=int, default=5)
    parser.add_argument("--tenant-id")
    parser.add_argument("--bot-id")
    args = parser.parse_args()
    if args.batch_size > 50:
        raise SystemExit("--batch-size maksimal 50 agar server tidak berat")
    result = asyncio.run(_index(args))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
