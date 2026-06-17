"""
One-time import: data/memory.json (4 profiles, 20 conversation summaries)
-> Postgres (user_memory_profiles, conversation_memory_summaries).

This is the historical-data carry-over for the JSON-to-Postgres long-term
memory migration (see memory_agent.py). Safe to run more than once -- uses
ON CONFLICT DO NOTHING so it never overwrites rows already written by live
traffic since the migration shipped.

Usage: python3 scripts/migrate_memory_json_to_postgres.py
"""
import asyncio
import json
import sys
from datetime import datetime
from pathlib import Path

import asyncpg

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import main  # noqa: E402

MEMORY_JSON_PATH = Path(__file__).resolve().parent.parent / "data" / "memory.json"


async def migrate(pool: asyncpg.Pool) -> None:
    data = json.loads(MEMORY_JSON_PATH.read_text())
    profiles = data.get("profiles", {})
    summaries = data.get("conversation_summaries", {})

    profiles_inserted = 0
    async with pool.acquire() as conn:
        for profile in profiles.values():
            facts_json = json.dumps(profile.get("facts", {}))
            result = await conn.execute(
                """
                INSERT INTO user_memory_profiles
                    (org_id, bot_id, end_user_id, facts, total_convs, created_at, updated_at)
                VALUES ($1, $2, $3, $4::jsonb, $5, $6, $7)
                ON CONFLICT (org_id, bot_id, end_user_id) DO NOTHING
                """,
                profile["org_id"], profile["bot_id"], profile["user_id"],
                facts_json, profile.get("total_convs", 0),
                datetime.fromisoformat(profile["created_at"]),
                datetime.fromisoformat(profile["updated_at"]),
            )
            if result.endswith("1"):
                profiles_inserted += 1

        summaries_inserted = 0
        for conv_id, summary in summaries.items():
            result = await conn.execute(
                """
                INSERT INTO conversation_memory_summaries (conversation_id, summary)
                VALUES ($1, $2)
                ON CONFLICT (conversation_id) DO NOTHING
                """,
                conv_id, summary,
            )
            if result.endswith("1"):
                summaries_inserted += 1

    print(f"Profiles: {profiles_inserted}/{len(profiles)} inserted (rest already present, skipped)")
    print(f"Summaries: {summaries_inserted}/{len(summaries)} inserted (rest already present, skipped)")


async def _run() -> None:
    pool = await asyncpg.create_pool(main.cfg.database_url.replace("+asyncpg", ""))
    try:
        await main.ensure_optional_schema(pool)
        await migrate(pool)
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(_run())
