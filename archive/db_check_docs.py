import os
import asyncio

import asyncpg
from dotenv import load_dotenv


async def main() -> None:
    load_dotenv(".env")
    url = (os.getenv("DATABASE_URL") or "").replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        raise SystemExit("DATABASE_URL kosong di .env")

    conn = await asyncpg.connect(url)
    try:
        rows = await conn.fetch(
            "select id, filename, status, error_msg, created_at "
            "from documents where status='failed' "
            "order by created_at desc limit 10"
        )
        print("failed_docs", len(rows))
        for r in rows:
            print(dict(r))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

