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
            "select id, filename, mime_type, status, chunk_count, error_msg, created_at, processed_at "
            "from documents order by created_at desc limit 10"
        )
        for r in rows:
            d = dict(r)
            d["id"] = str(d["id"])
            print(d)
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())

