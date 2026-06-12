"""
bn_platform — BotNesia Phase 2: Business / SaaS Platform layer.

Modul tambahan (add-on) di atas codebase BotNesia existing — TIDAK
menggantikan apa pun di main.py, hanya mendaftarkan router & helper baru.
Semua modul di sini memakai pola *factory function* (`build_xxx_router`)
yang menerima dependency (get_pool, get_current_user, dst) sebagai
argumen — sengaja dibuat begitu agar TIDAK ada circular import dengan
main.py (main.py mendefinisikan get_pool/get_current_user, lalu
"menyuntikkannya" ke router-router di sini saat startup).

Lihat bn_platform/ARCHITECTURE.md untuk peta lengkap & cara integrasi.

Catatan penamaan: paket ini sengaja diberi nama `bn_platform` (bukan
`platform`) supaya tidak bentrok dengan modul stdlib Python `platform`.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

__all__ = ["PLATFORM_VERSION"]

PLATFORM_VERSION = "2.0.0"
