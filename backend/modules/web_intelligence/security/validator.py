"""URL validation for Web Intelligence.

REUSES the platform's existing SSRF-safe validator (`tool_registry._validate_url`
+ `resolve_public_ips`) — the DNS-rebinding / private-IP / localhost defenses are
already implemented and tested there, so we do NOT reinvent or weaken them. This
module only adds an explicit, clearly-messaged scheme allow/deny layer on top
(block file://, ftp://, javascript:, data:, etc.) and a normalized public API.
"""
from __future__ import annotations

from urllib.parse import urlparse

# Reuse the platform SSRF gate (blocks private/loopback/link-local/reserved IPs,
# rejects non-http(s) schemes, and pins the resolved public IP against rebinding).
from tool_registry import _validate_url as _ssrf_validate_url

ALLOWED_SCHEMES = frozenset({"http", "https"})
# Explicitly denied (also caught by ALLOWED_SCHEMES, but listed for clear errors).
BLOCKED_SCHEMES = frozenset({
    "file", "ftp", "ftps", "sftp", "javascript", "data", "vbscript",
    "mailto", "tel", "about", "blob", "chrome", "view-source", "ws", "wss",
})
MAX_URL_LENGTH = 2048


def validate_url(url: str) -> tuple[bool, str]:
    """Return (ok, reason). ok=True only for a safe, public http(s) URL.

    Order: format/length → scheme allow/deny → SSRF (private IP/localhost/rebind).
    Never raises."""
    if not url or not isinstance(url, str):
        return False, "URL kosong atau bukan string."
    url = url.strip()
    if len(url) > MAX_URL_LENGTH:
        return False, f"URL terlalu panjang (> {MAX_URL_LENGTH} karakter)."
    if "\n" in url or "\r" in url or "\t" in url:
        return False, "URL mengandung karakter kontrol (newline/tab)."
    try:
        parsed = urlparse(url)
    except (ValueError, TypeError):
        return False, "URL tidak dapat diparse."
    scheme = (parsed.scheme or "").lower()
    if not scheme:
        return False, "URL tidak punya skema (butuh http:// atau https://)."
    if scheme in BLOCKED_SCHEMES:
        return False, f"Skema '{scheme}:' diblokir demi keamanan (hanya http/https)."
    if scheme not in ALLOWED_SCHEMES:
        return False, f"Skema '{scheme}:' tidak didukung (hanya http/https)."
    if not parsed.hostname:
        return False, "URL tidak punya host."
    # Final gate: platform SSRF check (localhost, private/reserved IP, DNS-rebind).
    return _ssrf_validate_url(url)


def is_valid_url(url: str) -> bool:
    return validate_url(url)[0]
