#!/usr/bin/env bash
# bn_platform/migrate.sh — Jalankan migrasi skema Phase 2 ke database existing
#
# Penggunaan:
#   DATABASE_URL=postgresql://user:pass@host:5432/botnesia ./bn_platform/migrate.sh
#
# Aman dijalankan ULANG (idempotent) — semua pernyataan memakai
# CREATE TABLE IF NOT EXISTS / ALTER TABLE ... ADD COLUMN IF NOT EXISTS /
# ON CONFLICT DO NOTHING, sehingga tidak ada efek samping pada data yang sudah ada.
#
# Urutan yang benar untuk database baru / reset:
#   psql "$DATABASE_URL" -f schema.sql
#   psql "$DATABASE_URL" -f intelligence/schema_intelligence.sql
#   DATABASE_URL=... ./bn_platform/migrate.sh  ← skrip ini

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SQL_FILE="$SCRIPT_DIR/schema_platform.sql"

: "${DATABASE_URL:?Set DATABASE_URL env var dulu, mis. export DATABASE_URL=postgresql://user:pass@host/db}"

echo "→ [migrate.sh] Memeriksa koneksi ke database ..."
psql "$DATABASE_URL" -c "SELECT version();" -tA | head -1

echo "→ [migrate.sh] Menjalankan $SQL_FILE ..."
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f "$SQL_FILE"

echo "→ [migrate.sh] Memverifikasi tabel kunci ..."
RESULT=$(psql "$DATABASE_URL" -tAc "
  SELECT string_agg(table_name, ', ' ORDER BY table_name)
  FROM information_schema.tables
  WHERE table_schema='public'
    AND table_name IN (
      'roles','permissions','role_permissions','user_roles',
      'plans','subscriptions','invoices','payment_history',
      'human_queue','channel_accounts','channels','channel_connections',
      'channel_messages','channel_events','channel_logs',
      'audit_logs','lead_scores',
      'marketplace_templates','tenant_template_installs',
      'revenue_snapshots','ai_answer_quality'
    )")

echo "   Tabel ditemukan: $RESULT"

EXPECTED=21
FOUND=$(echo "$RESULT" | tr ',' '\n' | wc -l | tr -d ' ')
if [ "$FOUND" -lt "$EXPECTED" ]; then
  echo "⚠  Peringatan: hanya $FOUND dari $EXPECTED tabel yang ditemukan — periksa error di atas."
else
  echo "✓  Semua $FOUND tabel Phase 2 terverifikasi."
fi

echo ""
echo "✓ [migrate.sh] Migrasi Phase 2 selesai."
echo "  Langkah berikutnya:"
echo "  1. pip install cryptography prometheus-client  (jika belum)"
echo "  2. python -c \"from cryptography.fernet import Fernet; print('CHANNEL_ENCRYPTION_KEY=' + Fernet.generate_key().decode())\" >> .env"
echo "  3. Set MIDTRANS_SERVER_KEY, XENDIT_SECRET_KEY, PLATFORM_ADMIN_EMAILS di .env"
echo "  4. Restart server: uvicorn main:app --host 0.0.0.0 --port 8000"
echo "  5. GET /api/billing/plans  — verifikasi 5 paket muncul"
