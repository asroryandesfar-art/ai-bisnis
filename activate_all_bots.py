import asyncio

import asyncpg

import main


async def _run() -> None:
    dsn = main.cfg.database_url.replace("+asyncpg", "")
    conn = await asyncpg.connect(dsn)
    try:
        n = await conn.execute("UPDATE bots SET status='active' WHERE status='inactive'")
    finally:
        await conn.close()
    print(f"OK: {n}")


if __name__ == "__main__":
    asyncio.run(_run())

