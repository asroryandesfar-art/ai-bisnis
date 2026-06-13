"""
whatsapp_embedded_signup.py — Klien Meta Graph API untuk WhatsApp Embedded Signup.

Referensi (diberikan pengguna, cek dokumentasi resmi untuk parameter terbaru):
- https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/overview
- https://developers.facebook.com/documentation/business-messaging/whatsapp/embedded-signup/implementation/

CATATAN KEJUJURAN: kedua halaman di atas dirender dinamis dan tidak bisa
diekstrak penuh oleh tool baca-halaman saat modul ini ditulis. Alur di bawah
(tukar `code` -> register nomor -> subscribe webhook WABA) mengikuti
dokumentasi WhatsApp Cloud API yang stabil dan dipakai luas. Jika Meta
mengubah parameter, sesuaikan fungsi di sini dan verifikasi ke dokumentasi
resmi via URL di atas.

Setiap fungsi mengembalikan dict `{"success": bool, "data": {...}}` atau
`{"success": False, "error": "..."}` — tidak pernah melempar exception untuk
error HTTP/API (supaya caller bisa mencatat connection_status="error" per
tenant tanpa try/except bertingkat).
"""
from __future__ import annotations

import httpx

GRAPH_BASE = "https://graph.facebook.com"
_TIMEOUT = 20.0


async def exchange_code_for_token(*, app_id: str, app_secret: str, code: str, api_version: str) -> dict:
    """Tukar authorization `code` dari FB.login() menjadi access token."""
    url = f"{GRAPH_BASE}/{api_version}/oauth/access_token"
    params = {"client_id": app_id, "client_secret": app_secret, "code": code}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.get(url, params=params)
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}
    if r.status_code >= 400:
        return {"success": False, "error": r.text[:300]}
    return {"success": True, "data": r.json()}


async def register_phone_number(*, phone_number_id: str, access_token: str, pin: str, api_version: str) -> dict:
    """Daftarkan nomor WhatsApp (two-step verification PIN) agar siap kirim/terima pesan."""
    url = f"{GRAPH_BASE}/{api_version}/{phone_number_id}/register"
    payload = {"messaging_product": "whatsapp", "pin": pin}
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, json=payload, headers=headers)
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}
    if r.status_code >= 400:
        return {"success": False, "error": r.text[:300]}
    return {"success": True, "data": r.json()}


async def subscribe_app_to_waba(*, waba_id: str, access_token: str, api_version: str) -> dict:
    """Subscribe app BotNesia ke webhook WhatsApp Business Account (WABA) milik tenant."""
    url = f"{GRAPH_BASE}/{api_version}/{waba_id}/subscribed_apps"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.post(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}
    if r.status_code >= 400:
        return {"success": False, "error": r.text[:300]}
    return {"success": True, "data": r.json()}


async def unsubscribe_app_from_waba(*, waba_id: str, access_token: str, api_version: str) -> dict:
    """Lepas subscription app dari webhook WABA (dipakai saat disconnect)."""
    url = f"{GRAPH_BASE}/{api_version}/{waba_id}/subscribed_apps"
    headers = {"Authorization": f"Bearer {access_token}"}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.delete(url, headers=headers)
    except httpx.HTTPError as exc:
        return {"success": False, "error": str(exc)}
    if r.status_code >= 400:
        return {"success": False, "error": r.text[:300]}
    return {"success": True, "data": r.json()}
