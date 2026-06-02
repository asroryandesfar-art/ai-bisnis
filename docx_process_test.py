import asyncio
import os
import uuid

from dotenv import load_dotenv

import asyncpg


async def main() -> None:
    load_dotenv(".env")
    url = (os.getenv("DATABASE_URL") or "").replace("postgresql+asyncpg://", "postgresql://")
    if not url:
        raise SystemExit("DATABASE_URL kosong di .env")

    docx_path = "BotNesia_Knowledge_Base_Template.docx"
    with open(docx_path, "rb") as f:
        content = f.read()

    pool = await asyncpg.create_pool(url)
    try:
        # pick any org_id + bot_id that exists
        async with pool.acquire() as conn:
            bot = await conn.fetchrow("select id, org_id from bots limit 1")
            if not bot:
                raise SystemExit("Tidak ada bot di DB. Buat bot dulu via dashboard.")
            bot_id = str(bot["id"])
            org_id = str(bot["org_id"])

            doc_id = str(uuid.uuid4())
            await conn.execute(
                "insert into documents (id, org_id, bot_id, filename, file_size, mime_type, status) "
                "values ($1,$2,$3,$4,$5,$6,'pending')",
                doc_id,
                org_id,
                bot_id,
                docx_path,
                len(content),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

        from main import _process_document_sync  # local import so it uses current code

        await _process_document_sync(
            pool,
            doc_id,
            content,
            "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        )

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "select status, chunk_count, error_msg from documents where id=$1", doc_id
            )
            print(dict(row))
    finally:
        await pool.close()


if __name__ == "__main__":
    asyncio.run(main())

