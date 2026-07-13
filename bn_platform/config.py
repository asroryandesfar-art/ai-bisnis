"""
bn_platform/config.py — pengaturan khusus Phase 2 (Business Platform).

Membaca .env yang sama (pydantic-settings membaca env var berdasarkan
nama field, jadi tidak perlu prefix khusus) — pola identik dengan
intelligence/config.py supaya tidak menyentuh class Settings di main.py.
"""
# from __future__ import annotations  # dihapus: menyebabkan Depends(closure_var) gagal di-resolve oleh FastAPI get_type_hints()

from pydantic_settings import BaseSettings, SettingsConfigDict


class PlatformSettings(BaseSettings):
    # ── Core app / Meta OAuth ──
    app_url: str = "http://127.0.0.1:8000"
    secret_key: str = "change-me-in-production"
    meta_app_id: str = ""
    meta_app_secret: str = ""
    meta_api_version: str = "v21.0"
    meta_oauth_redirect_uri: str = ""
    meta_verify_token: str = ""

    # ── Midtrans (Snap API) — https://docs.midtrans.com/docs/snap-snap-integration-guide ──
    midtrans_server_key:    str = ""
    midtrans_client_key:    str = ""
    midtrans_is_production: bool = False

    # ── Xendit (Invoices API) — https://developers.xendit.co/api-reference/#create-invoice ──
    xendit_secret_key:      str = ""
    xendit_callback_token:  str = ""

    # ── Telegram Bot API (Omnichannel) ──
    telegram_bot_token:     str = ""
    telegram_webhook_secret: str = ""

    # ── Platform-owned Meta channels ──
    # Pelanggan tidak memasukkan token. Operator mengelola satu akun provider
    # untuk tiap channel melalui environment/secret deployment.
    instagram_access_token: str = ""
    instagram_account_id: str = ""
    facebook_page_access_token: str = ""
    facebook_page_id: str = ""

    # ── Enkripsi kredensial channel (Fernet — urlsafe base64, 32 byte) ──
    # generate: python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
    channel_encryption_key: str = ""

    # ── SLA Human Handoff (menit, dipakai utk hitung sla_due_at) ──
    handoff_sla_minutes_urgent: int = 15
    handoff_sla_minutes_high:   int = 60
    handoff_sla_minutes_medium: int = 240
    handoff_sla_minutes_low:    int = 1440

    # ── Trial & billing ──
    trial_days: int = 14
    invoice_due_days: int = 3
    platform_fee_currency: str = "IDR"

    # Kontak sales untuk paket Enterprise/custom (quote flow "Hubungi Sales").
    # Dipakai frontend (mailto) & guard checkout. Ubah via env SALES_EMAIL.
    sales_email: str = "sales@botnesia.id"

    # Operator-only Revenue Intelligence
    platform_admin_emails: str = ""
    monthly_marketing_spend_idr: int = 0
    founder_usd_to_idr: int = 16000
    local_billing_enabled: bool = False

    # ── Observability (/metrics scrape oleh Prometheus) ──
    # Jika diisi, endpoint /metrics mewajibkan header `Authorization: Bearer <token>`
    # — kosongkan utk lab/dev, isi sebelum expose ke jaringan publik.
    metrics_auth_token: str = ""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore")


cfg = PlatformSettings()
