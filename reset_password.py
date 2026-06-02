import asyncio
import sys

import asyncpg

import main


async def _run(email: str, new_password: str) -> None:
    email = email.strip().lower()
    dsn = main.cfg.database_url.replace("+asyncpg", "")

    conn = await asyncpg.connect(dsn)
    try:
        user = await conn.fetchrow("SELECT id, email FROM users WHERE email=$1", email)
        if not user:
            raise SystemExit(f"User tidak ditemukan untuk email: {email}")

        new_hash = main.hash_password(new_password)
        await conn.execute(
            "UPDATE users SET hashed_password=$2, is_active=TRUE WHERE id=$1",
            str(user["id"]),
            new_hash,
        )
    finally:
        await conn.close()

    print(f"OK: password direset untuk {email}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print("Usage: python reset_password.py <email> <new_password>")
        raise SystemExit(2)
    asyncio.run(_run(sys.argv[1], sys.argv[2]))

