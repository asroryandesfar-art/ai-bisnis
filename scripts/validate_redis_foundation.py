"""Validasi fondasi P0 terhadap Redis-server NYATA (via redislite, tanpa sudo).

Membuktikan RedisStateStore & konsumennya benar di Redis asli — termasuk hal yang
TAK bisa dibuktikan fakeredis: atomicity di bawah konkurensi nyata & TTL server.

Jalankan: python3 scripts/validate_redis_foundation.py   (butuh `pip install redislite`)
Idempoten, tak menyentuh DB/produksi. Exit 0 = semua PASS.
"""
import asyncio
import sys

import redislite
import redis.asyncio as ra

sys.path.insert(0, ".")
from platform_state.redis_store import RedisStateStore  # noqa: E402
from platform_state import set_state_store               # noqa: E402


def _client(sock):
    return ra.Redis(unix_socket_path=sock, decode_responses=True)


async def main() -> int:
    server = redislite.Redis()                 # spawn redis-server ASLI
    sock = server.socket_file
    ver = server.info().get("redis_version")
    print(f"== Redis NYATA via redislite (v{ver}, socket={sock}) ==\n")

    A = RedisStateStore(_client(sock))         # "worker A"
    B = RedisStateStore(_client(sock))         # "worker B" (koneksi berbeda, server sama)
    results = []

    def check(name, cond):
        results.append(cond)
        print(f"[{'PASS' if cond else 'FAIL'}] {name}")

    try:
        # 0) jalur wiring produksi: build_redis_store(from_url) + healthcheck
        from platform_state import build_redis_store
        prod = build_redis_store(f"unix://{sock}")
        check("build_redis_store(from_url) + healthcheck (jalur startup produksi)",
              await prod.healthcheck())
        await prod._r.aclose()

        # 1) rate-limit shared lintas-koneksi
        r1 = await A.rate_incr("rl:x", window_s=60, limit=2)
        r2 = await A.rate_incr("rl:x", window_s=60, limit=2)
        r3 = await B.rate_incr("rl:x", window_s=60, limit=2)
        check("rate-limit shared cross-connection", r1[0] and r2[0] and r3 == (False, 2))

        # 2) ATOMICITY di bawah 200 request konkuren: limit 10 → TEPAT 10 allowed
        await A._r.delete("rl:c")
        outs = await asyncio.gather(*[A.rate_incr("rl:c", window_s=60, limit=10) for _ in range(200)])
        allowed = sum(1 for ok, _ in outs if ok)
        check(f"rate_incr atomik di bawah 200 concurrent (allowed={allowed}, harus 10)", allowed == 10)

        # 3) TTL server NYATA (bukan mock): set 1 dtk → hilang setelah lewat
        await A.set("k", "v", ttl_s=1)
        before = await B.get("k")
        await asyncio.sleep(1.2)
        after = await B.get("k")
        check("TTL server nyata (set 1s → hilang)", before == "v" and after is None)

        # 4) distributed lock: NX + token-guard + TTL nyata
        got_a = await A.acquire_lock("L", ttl_s=30, token="A")
        got_b = await B.acquire_lock("L", ttl_s=30, token="B")
        check("lock NX (A dapat, B tidak)", got_a and not got_b)
        rel_bad = await B.release_lock("L", token="B")
        rel_ok = await A.release_lock("L", token="A")
        check("lock token-guard release", (not rel_bad) and rel_ok)
        await A.acquire_lock("L2", ttl_s=1, token="A")
        await asyncio.sleep(1.2)
        check("lock TTL nyata → bisa direbut", await B.acquire_lock("L2", ttl_s=5, token="B"))

        # 5) circuit-breaker lintas-worker (state lokal terpisah, Redis shared)
        import ai_providers.router as router
        ba, bb = router._CircuitBreaker(), router._CircuitBreaker()
        set_state_store(A)
        for _ in range(3):
            await ba.fail("gemini")
        set_state_store(B)
        check("circuit-breaker open shared cross-worker", await bb.is_open("gemini"))
        set_state_store(None)

        # 6) working-memory STM lintas-worker
        from memory_agent import MemoryStore
        sa, sb = MemoryStore(), MemoryStore()
        set_state_store(A)
        await sa.add_to_stm("c1", "user", "halo dunia")
        set_state_store(B)
        rec = await sb.get_recent("c1")
        set_state_store(None)
        check("working-memory STM shared cross-worker", [m["content"] for m in rec] == ["halo dunia"])

    finally:
        try:
            await A._r.aclose(); await B._r.aclose()
        except Exception:
            pass
        try:
            server.shutdown()
        except Exception:
            pass

    ok = all(results)
    print(f"\n== RESULT: {'SEMUA PASS ✅' if ok else 'ADA YANG GAGAL ❌'} ({sum(results)}/{len(results)}) ==")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
