#!/usr/bin/env python3
"""
test_instagram_webhook.py — Kirim payload Instagram DM simulasi ke webhook BotNesia.

Penggunaan:
    python3 test_instagram_webhook.py
    python3 test_instagram_webhook.py --url http://127.0.0.1:8000 --ig-id 17841447104071131 --text "Halo"

Memverifikasi END-TO-END:
    webhook menerima → signature valid → IG User ID cocok DB → pipeline chat → reply.
"""
import argparse
import hashlib
import hmac
import json
import sys
import time

import httpx


def main():
    ap = argparse.ArgumentParser(description="Test Instagram DM webhook BotNesia")
    ap.add_argument("--url", default="http://127.0.0.1:8000", help="Base URL BotNesia")
    ap.add_argument("--endpoint", default="/webhooks/meta", help="Webhook endpoint path")
    ap.add_argument("--ig-id", default="17841447104071131", help="Instagram Business ID (recipient)")
    ap.add_argument("--sender", default="999888777", help="Sender IG user ID (test)")
    ap.add_argument("--text", default="Halo, ini test DM Instagram ke BotNesia", help="Pesan DM")
    ap.add_argument("--secret", default=None, help="META_APP_SECRET (auto-detect dari .env jika kosong)")
    args = ap.parse_args()

    app_secret = args.secret
    if not app_secret:
        try:
            from bn_platform.config import cfg
            app_secret = cfg.meta_app_secret
        except Exception:
            print("ERROR: tidak bisa baca META_APP_SECRET. Pass --secret atau jalankan dari direktori project.")
            sys.exit(1)

    if not app_secret:
        print("ERROR: META_APP_SECRET kosong. Webhook akan menolak (fail-closed).")
        sys.exit(1)

    mid = f"test_ig_{int(time.time())}"
    payload = {
        "object": "instagram",
        "entry": [{
            "id": args.ig_id,
            "messaging": [{
                "sender": {"id": args.sender},
                "recipient": {"id": args.ig_id},
                "timestamp": int(time.time() * 1000),
                "message": {"mid": mid, "text": args.text},
            }],
        }],
    }
    body = json.dumps(payload).encode("utf-8")
    sig = "sha256=" + hmac.new(app_secret.encode("utf-8"), body, hashlib.sha256).hexdigest()
    url = args.url.rstrip("/") + args.endpoint

    print(f"=== TEST Instagram DM Webhook ===")
    print(f"  URL      : {url}")
    print(f"  IG ID    : {args.ig_id}")
    print(f"  sender   : {args.sender}")
    print(f"  mid      : {mid}")
    print(f"  text     : {args.text}")
    print(f"  signature: {sig[:30]}...")
    print()

    try:
        r = httpx.post(
            url,
            content=body,
            headers={"Content-Type": "application/json", "X-Hub-Signature-256": sig},
            timeout=60,
        )
    except Exception as exc:
        print(f"FAIL: tidak bisa terhubung ke {url}: {exc}")
        sys.exit(1)

    print(f"HTTP {r.status_code} -> {r.text}")

    if r.status_code == 200:
        print()
        print("Webhook DITERIMA. Cek log server:")
        print("  journalctl --user -u botnesia-api.service --since '15 sec ago' | grep -E 'WEBHOOK|entry|Route inbound'")
        print()
        print("Jika muncul '=== WEBHOOK RECEIVED === object=instagram' → inbound BERFUNGSI.")
        print("Jika muncul 'capability to make this API call' (code 3) → app masih Development mode,")
        print("  reply gagal tapi inbound tetap sampai. Ubah app ke Live setelah App Review.")
    elif r.status_code == 403:
        print("\nFAIL: signature invalid — META_APP_SECRET di .env tidak cocok.")
    elif r.status_code == 503:
        print("\nFAIL: META_APP_SECRET belum dikonfigurasi di server.")
    else:
        print(f"\nFAIL: HTTP {r.status_code}")

    sys.exit(0 if r.status_code == 200 else 1)


if __name__ == "__main__":
    main()
