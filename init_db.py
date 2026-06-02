import asyncio
from pathlib import Path

import asyncpg

import main


async def _run() -> None:
    dsn = main.cfg.database_url.replace("+asyncpg", "")
    schema_path = Path(__file__).resolve().parent / "schema.sql"
    if not schema_path.exists():
        raise SystemExit("schema.sql tidak ditemukan")

    sql = schema_path.read_text(encoding="utf-8")
    conn = await asyncpg.connect(dsn)
    try:
        exists = await conn.fetchval("SELECT to_regclass('public.organizations')")
        if exists:
            print("SKIP: schema sudah ada (tabel organizations ditemukan)")
            return
        await conn.execute(sql)
    finally:
        await conn.close()

    print("OK: schema.sql sudah dijalankan")


if __name__ == "__main__":
    asyncio.run(_run())
