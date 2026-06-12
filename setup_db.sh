#!/usr/bin/env bash
# setup_db.sh — Setup database BotNesia lengkap (Phase 1 + Phase 2)
# Jalankan SEKALI setelah PostgreSQL aktif:
#   chmod +x setup_db.sh && ./setup_db.sh
#
# DATABASE_URL dibaca dari .env secara otomatis.

set -euo pipefail
cd "$(dirname "$0")"

echo ""
echo "=================================================="
echo "  BotNesia — Database Setup"
echo "=================================================="
echo ""

# ── 1. Baca DATABASE_URL dari .env ──────────────────────────────
if [ -f .env ]; then
    export $(grep -v '^#' .env | grep '=' | grep -v '^\s*$' | xargs) 2>/dev/null || true
fi

# Konversi format asyncpg → psql (hapus +asyncpg)
DB_URL="${DATABASE_URL/+asyncpg/}"
if [ -z "$DB_URL" ]; then
    echo "❌ DATABASE_URL tidak ditemukan di .env"
    exit 1
fi
echo "→ Database: ${DB_URL//:*@/:***@}"

# ── 2. Cek koneksi database ─────────────────────────────────────
echo ""
echo "→ Mengecek koneksi PostgreSQL..."
python3 - <<PYCHECK
import asyncio, asyncpg, os, sys

async def check():
    url = os.environ.get("DATABASE_URL","").replace("+asyncpg","")
    try:
        conn = await asyncio.wait_for(asyncpg.connect(url), timeout=5)
        ver = await conn.fetchval("SELECT version()")
        await conn.close()
        print(f"  ✓ Terhubung: {ver[:60]}")
    except asyncio.TimeoutError:
        print("  ❌ Koneksi timeout — pastikan PostgreSQL sudah berjalan")
        sys.exit(1)
    except Exception as e:
        print(f"  ❌ Koneksi gagal: {e}")
        print("")
        print("  Jalankan dulu:")
        print("    sudo systemctl start postgresql")
        print("    sudo -u postgres psql -c \"CREATE USER botnesia WITH PASSWORD 'admin123';\"")
        print("    sudo -u postgres psql -c \"CREATE DATABASE botnesia OWNER botnesia;\"")
        print("    sudo -u postgres psql -d botnesia -c \"CREATE EXTENSION IF NOT EXISTS \\\"uuid-ossp\\\";\"")
        print("    sudo -u postgres psql -d botnesia -c \"CREATE EXTENSION IF NOT EXISTS vector;\"")
        sys.exit(1)

asyncio.run(check())
PYCHECK

# ── 3. Jalankan skema SQL ────────────────────────────────────────
echo ""
echo "→ Menjalankan schema.sql (skema inti)..."
psql "$DB_URL" -v ON_ERROR_STOP=1 -f schema.sql
echo "  ✓ schema.sql selesai"

echo ""
echo "→ Menjalankan intelligence/schema_intelligence.sql (Phase 1)..."
psql "$DB_URL" -v ON_ERROR_STOP=1 -f intelligence/schema_intelligence.sql
echo "  ✓ schema_intelligence.sql selesai"

echo ""
echo "→ Menjalankan bn_platform/schema_platform.sql (Phase 2)..."
psql "$DB_URL" -v ON_ERROR_STOP=1 -f bn_platform/schema_platform.sql
echo "  ✓ schema_platform.sql selesai"

# ── 4. Verifikasi tabel ──────────────────────────────────────────
echo ""
echo "→ Verifikasi tabel..."
python3 - <<PYVERIFY
import asyncio, asyncpg, os, sys

REQUIRED = [
    # inti
    "organizations","users","bots","conversations","messages",
    # phase 1
    "faq_entries","customer_profiles","sales_signals",
    # phase 2
    "roles","permissions","subscriptions","plans","invoices",
    "human_queue","channel_accounts","audit_logs",
    "lead_scores","marketplace_templates","revenue_snapshots",
]

async def check():
    url = os.environ.get("DATABASE_URL","").replace("+asyncpg","")
    conn = await asyncpg.connect(url)
    rows = await conn.fetch(
        "SELECT table_name FROM information_schema.tables WHERE table_schema='public'"
    )
    found = {r['table_name'] for r in rows}
    ok, missing = [], []
    for t in REQUIRED:
        (ok if t in found else missing).append(t)
    print(f"  ✓ {len(ok)}/{len(REQUIRED)} tabel ditemukan")
    if missing:
        print(f"  ⚠  Belum ada: {', '.join(missing)}")
    else:
        print("  ✓ Semua tabel wajib tersedia!")
    await conn.close()

asyncio.run(check())
PYVERIFY

# ── 5. Cek .env lengkap ──────────────────────────────────────────
echo ""
echo "→ Cek konfigurasi .env..."
python3 - <<PYENV
import os
checks = {
    "DATABASE_URL": bool(os.environ.get("DATABASE_URL")),
    "SECRET_KEY": bool(os.environ.get("SECRET_KEY")),
    "GROQ_API_KEY": bool(os.environ.get("GROQ_API_KEY")),
    "CHANNEL_ENCRYPTION_KEY": bool(os.environ.get("CHANNEL_ENCRYPTION_KEY")),
    "PLATFORM_ADMIN_EMAILS": bool(os.environ.get("PLATFORM_ADMIN_EMAILS")),
}
for k, v in checks.items():
    icon = "✓" if v else "⚠ "
    print(f"  {icon}  {k}: {'SET' if v else 'KOSONG (opsional tapi disarankan)'}")
PYENV

echo ""
echo "=================================================="
echo "  ✓ Database setup selesai!"
echo ""
echo "  Jalankan server dengan:"
echo "    python3 run_server.py"
echo "  atau:"
echo "    uvicorn main:app --host 0.0.0.0 --port 8000 --reload"
echo "=================================================="
echo ""
