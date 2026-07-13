"""Integration routes (Gmail, Meta: WhatsApp/Facebook/Instagram) + Meta webhooks.

Extracted from main.py. Handlers reference ~55 main-level helpers/models (many
monkeypatched by tests) via `main.X` (late binding). Helpers/models stay in
main; main re-exports each handler by name (tests direct-call the handlers)."""
import main
from fastapi import APIRouter


def build_integrations_router() -> APIRouter:
    router = APIRouter()

    @router.get("/integrations")
    async def integrations_status(
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        gmail = integ.get("gmail") or {}
        meta = integ.get("meta") or {}
        return {
            "gmail": {
                "connected": bool(gmail.get("refresh_token") or gmail.get("access_token")),
                "email": gmail.get("email"),
                "bot_id": gmail.get("bot_id"),
            },
            "meta": {
                "connected": bool(meta.get("wa_token") or meta.get("page_token") or meta.get("ig_token")),
                "wa_phone_number_id": meta.get("wa_phone_number_id"),
            },
            "webhook": {
                "meta_url": "/webhooks/meta",
            },
        }

    @router.post("/integrations/meta")
    async def save_meta_integration(
        body: main.MetaIntegrationReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        # Simpan terenkripsi di DB (fallback: file JSON).
        meta = {
            "wa_token": body.wa_token or "",
            "wa_phone_number_id": body.wa_phone_number_id or "",
            "page_token": body.page_token or "",
            "ig_token": body.ig_token or "",
            "default_to_number": body.default_to_number or "",
            "wa_bot_id": body.wa_bot_id or "",
            "updated_at": main.datetime.now(main.timezone.utc).isoformat(),
        }
        await main._set_integration_auto(pool, str(user["org_id"]), "meta", meta)

        # Optional: kalau user sekalian isi wa_bot_id, simpan mapping untuk inbound routing.
        if meta["wa_phone_number_id"] and meta["wa_bot_id"]:
            try:
                await main.db_set_meta_phone_mapping(
                    pool,
                    phone_number_id=meta["wa_phone_number_id"].strip(),
                    org_id=str(user["org_id"]),
                    bot_id=meta["wa_bot_id"].strip(),
                )
            except Exception:
                pass
        return {
            "message": "Meta integration tersimpan",
            "meta": {
                "wa_phone_number_id": meta["wa_phone_number_id"] or None,
                "wa_token": main._mask_secret(meta["wa_token"]),
                "page_token": main._mask_secret(meta["page_token"]),
                "ig_token": main._mask_secret(meta["ig_token"]),
                "default_to_number": meta["default_to_number"] or None,
                "wa_bot_id": meta["wa_bot_id"] or None,
            },
        }

    @router.post("/integrations/meta/map-bot")
    async def meta_map_bot(
        body: main.MetaMapBotReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        # validate bot belongs to org
        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
            body.bot_id, user["org_id"],
        )
        if not bot:
            raise main.HTTPException(404, "Bot tidak ditemukan untuk org ini")

        await main.db_set_meta_phone_mapping(
            pool,
            phone_number_id=body.wa_phone_number_id.strip(),
            org_id=str(user["org_id"]),
            bot_id=str(body.bot_id),
        )
        # keep a per-org map for UI/debug (encrypted)
        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        meta_map = dict(integ.get("meta_map") or {})
        meta_map[body.wa_phone_number_id.strip()] = str(body.bot_id)
        await main._set_integration_auto(pool, str(user["org_id"]), "meta_map", meta_map)
        return {"message": "Mapping tersimpan", "meta_map": meta_map}

    @router.post("/integrations/meta/send-test")
    async def meta_send_test(
        body: main.MetaSendTestReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        meta = integ.get("meta") or {}
        token = (meta.get("wa_token") or "").strip()
        phone_id = (meta.get("wa_phone_number_id") or "").strip()
        if not token or not phone_id:
            raise main.HTTPException(400, "Meta WA token / phone number id belum diset")

        url = f"https://graph.facebook.com/v19.0/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
        payload = {
            "messaging_product": "whatsapp",
            "to": body.to_number.strip(),
            "type": "text",
            "text": {"body": body.text},
        }
        async with main.httpx.AsyncClient(timeout=20) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                raise main.HTTPException(400, f"Meta send gagal: {r.text[:300]}")
            return {"status": "ok", "response": r.json()}

    @router.post("/integrations/meta/send-template")
    async def meta_send_template(
        body: main.MetaSendTemplateReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        meta = integ.get("meta") or {}
        token = (meta.get("wa_token") or "").strip()
        phone_id = (meta.get("wa_phone_number_id") or "").strip()
        if not token or not phone_id:
            raise main.HTTPException(400, "Meta WA token / phone number id belum diset")

        api_ver = (main.cfg.meta_api_version or "v19.0").strip() or "v19.0"
        url = f"https://graph.facebook.com/{api_ver}/{phone_id}/messages"
        headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

        tpl: dict = {
            "name": (body.template_name or "hello_world").strip(),
            "language": {"code": (body.language_code or "en_US").strip()},
        }
        if body.components:
            tpl["components"] = body.components

        payload = {
            "messaging_product": "whatsapp",
            "to": body.to_number.strip(),
            "type": "template",
            "template": tpl,
        }
        async with main.httpx.AsyncClient(timeout=25) as client:
            r = await client.post(url, headers=headers, json=payload)
            if r.status_code >= 400:
                raise main.HTTPException(400, f"Meta template send gagal: {r.text[:800]}")
            return {"status": "ok", "response": r.json()}

    @router.get("/integrations/whatsapp/connect")
    async def whatsapp_embedded_connect(
        bot_id: str,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        """Mulai flow Meta WhatsApp Embedded Signup untuk satu agent (bot).

        Embedded Signup berbasis FB JS SDK (popup), bukan redirect — jadi
        endpoint ini mengembalikan konfigurasi yang dibutuhkan frontend untuk
        memanggil FB.init() + FB.login({config_id, response_type:'code',
        override_default_response_type:true, ...}), bukan `auth_url`.
        """
        if not main.cfg.meta_app_id or not main.cfg.meta_embedded_signup_config_id:
            raise main.HTTPException(400, "META_APP_ID / META_EMBEDDED_SIGNUP_CONFIG_ID belum diisi di .env")

        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
            bot_id, user["org_id"],
        )
        if not bot:
            raise main.HTTPException(404, "Bot tidak ditemukan untuk org ini")

        state = main.secrets.token_urlsafe(24)
        # `redirect_uri` direuse untuk membawa bot_id ke /callback — Embedded
        # Signup adalah popup flow (tidak ada redirect URI sungguhan).
        await main.db_set_oauth_state(
            pool,
            provider="whatsapp_embedded",
            state=state,
            org_id=str(user["org_id"]),
            redirect_uri=str(bot_id),
        )

        return {
            "app_id": main.cfg.meta_app_id,
            "config_id": main.cfg.meta_embedded_signup_config_id,
            "graph_api_version": main.cfg.meta_api_version,
            "state": state,
            "bot_id": str(bot_id),
        }

    @router.post("/integrations/whatsapp/callback")
    async def whatsapp_embedded_callback(
        body: main.WhatsAppEmbeddedCallbackReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        """Selesaikan Embedded Signup: tukar code -> register nomor -> subscribe
        webhook WABA -> simpan kredensial terenkripsi per tenant (org_id+bot_id)."""
        org_id, bot_id = await main.db_pop_oauth_state(pool, provider="whatsapp_embedded", state=body.state)
        if not org_id or not bot_id:
            raise main.HTTPException(400, "State tidak valid/sudah expired")
        if org_id != str(user["org_id"]):
            raise main.HTTPException(403, "State ini bukan milik tenant Anda")

        bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id)
        if not bot:
            raise main.HTTPException(404, "Bot tidak ditemukan untuk org ini")

        if not main.cfg.meta_app_id or not main.cfg.meta_app_secret:
            raise main.HTTPException(400, "META_APP_ID / META_APP_SECRET belum diisi di .env")

        api_ver = main.cfg.meta_api_version

        token_res = await main.wa_exchange_code_for_token(
            app_id=main.cfg.meta_app_id, app_secret=main.cfg.meta_app_secret, code=body.code, api_version=api_ver,
        )
        if not token_res.get("success"):
            await main.db_set_whatsapp_account(
                pool, org_id=org_id, bot_id=bot_id,
                waba_id=body.waba_id, phone_number_id=body.phone_number_id, business_id=body.business_id or "",
                customer_access_token="", token_expires_at=None, connection_status="error",
                secret_key=main.cfg.effective_encryption_key,
            )
            raise main.HTTPException(400, f"Tukar code dengan Meta gagal: {token_res.get('error')}")

        token_data = token_res.get("data") or {}
        access_token = token_data.get("access_token", "")
        expires_in = token_data.get("expires_in")
        token_expires_at = None
        if expires_in:
            try:
                token_expires_at = main.datetime.now(main.timezone.utc) + main.timedelta(seconds=int(expires_in))
            except (TypeError, ValueError):
                token_expires_at = None

        reg_res = await main.wa_register_phone_number(
            phone_number_id=body.phone_number_id, access_token=access_token,
            pin=main.cfg.meta_register_pin, api_version=api_ver,
        )
        sub_res = await main.wa_subscribe_app_to_waba(
            waba_id=body.waba_id, access_token=access_token, api_version=api_ver,
        )

        if reg_res.get("success") and sub_res.get("success"):
            connection_status = "connected"
            error_detail = None
        else:
            connection_status = "error"
            error_detail = reg_res.get("error") or sub_res.get("error")

        # Simpan apa pun hasilnya — supaya /status bisa menunjukkan connection_status
        # ("connected" atau "error") tanpa kehilangan waba_id/phone_number_id yang
        # sudah dipilih user di popup Embedded Signup.
        await main.db_set_whatsapp_account(
            pool, org_id=org_id, bot_id=bot_id,
            waba_id=body.waba_id, phone_number_id=body.phone_number_id, business_id=body.business_id or "",
            customer_access_token=access_token, token_expires_at=token_expires_at,
            connection_status=connection_status, secret_key=main.cfg.effective_encryption_key,
        )

        if connection_status != "connected":
            raise main.HTTPException(400, f"WhatsApp terautentikasi tapi setup gagal: {error_detail}")

        # Routing inbound webhook -> org/bot yang benar.
        await main.db_set_meta_phone_mapping(
            pool, phone_number_id=body.phone_number_id, org_id=org_id, bot_id=bot_id,
        )

        return {
            "message": "WhatsApp berhasil terhubung",
            "tenant_id": org_id,
            "bot_id": bot_id,
            "waba_id": body.waba_id,
            "phone_number_id": body.phone_number_id,
            "business_id": body.business_id,
            "connection_status": connection_status,
            "token_expires_at": token_expires_at.isoformat() if token_expires_at else None,
        }

    @router.get("/integrations/whatsapp/status")
    async def whatsapp_embedded_status(
        bot_id: str | None = None,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        org_id = str(user["org_id"])
        if bot_id:
            bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, org_id)
            if not bot:
                raise main.HTTPException(404, "Bot tidak ditemukan untuk org ini")
            acc = await main.db_get_whatsapp_account(pool, org_id=org_id, bot_id=bot_id, secret_key=main.cfg.effective_encryption_key)
            if not acc:
                return {
                    "tenant_id": org_id, "bot_id": str(bot_id),
                    "connected": False, "connection_status": "disconnected",
                }
            return main._whatsapp_account_public(acc)

        accounts = await main.db_get_whatsapp_accounts(pool, org_id=org_id, secret_key=main.cfg.effective_encryption_key)
        return {"accounts": [main._whatsapp_account_public(a) for a in accounts]}

    @router.post("/integrations/whatsapp/disconnect")
    async def whatsapp_embedded_disconnect(
        body: main.WhatsAppEmbeddedDisconnectReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        org_id = str(user["org_id"])
        bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", body.bot_id, org_id)
        if not bot:
            raise main.HTTPException(404, "Bot tidak ditemukan untuk org ini")

        acc = await main.db_get_whatsapp_account(pool, org_id=org_id, bot_id=body.bot_id, secret_key=main.cfg.effective_encryption_key)
        if not acc:
            raise main.HTTPException(404, "WhatsApp belum terhubung untuk bot ini")

        # Best-effort: lepas subscription webhook WABA di sisi Meta.
        if acc.get("customer_access_token") and acc.get("waba_id"):
            try:
                await main.wa_unsubscribe_app_from_waba(
                    waba_id=acc["waba_id"], access_token=acc["customer_access_token"],
                    api_version=main.cfg.meta_api_version,
                )
            except Exception:
                pass

        if acc.get("phone_number_id"):
            try:
                await main.db_clear_meta_phone_mapping(pool, phone_number_id=acc["phone_number_id"])
            except Exception:
                pass

        await main.db_clear_whatsapp_account(pool, org_id=org_id, bot_id=body.bot_id)
        return {
            "message": "WhatsApp diputuskan",
            "tenant_id": org_id, "bot_id": body.bot_id,
            "connection_status": "disconnected",
        }

    @router.delete("/integrations/{key}")
    async def delete_integration(
        key: str,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        if key not in {"gmail", "meta"}:
            raise main.HTTPException(400, "Integration key tidak valid")
        await main._clear_integration_auto(pool, str(user["org_id"]), key)
        return {"message": "Integration dihapus", "key": key}

    @router.post("/integrations/gmail/start")
    async def gmail_start_oauth(
        request: main.Request,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        if not main.cfg.gmail_client_id or not main.cfg.gmail_client_secret:
            raise main.HTTPException(400, "GMAIL_CLIENT_ID/SECRET belum diisi di .env")

        state = main.secrets.token_urlsafe(24)

        # Redirect URI harus match persis dengan yang didaftarkan di Google Cloud OAuth Client.
        base = str(request.base_url).rstrip("/")
        dynamic_redirect_uri = base + "/integrations/gmail/callback"

        configured = (main.cfg.gmail_redirect_uri or "").strip()
        # Kalau redirect_uri di .env berbeda host/port dari origin yang dipakai user,
        # lebih aman pakai dynamic URI agar tidak mismatch (user cukup whitelist URI ini di Google Console).
        redirect_uri = configured if (configured and configured == dynamic_redirect_uri) else dynamic_redirect_uri

        # Simpan state di DB (tidak terenkripsi) supaya callback bisa cari org_id tanpa scan file.
        try:
            await main.db_set_oauth_state(
                pool,
                provider="gmail",
                state=state,
                org_id=str(user["org_id"]),
                redirect_uri=redirect_uri,
            )
        except Exception:
            # fallback lama: file store
            main.set_integration(
                str(user["org_id"]),
                "gmail_oauth",
                {
                    "state": state,
                    "redirect_uri": redirect_uri,
                    "created_at": main.datetime.now(main.timezone.utc).isoformat(),
                },
            )

        params = {
            "client_id": main.cfg.gmail_client_id,
            "redirect_uri": redirect_uri,
            "response_type": "code",
            # NOTE: gmail.modify memungkinkan membaca + mark-as-read. Untuk auto-reply perlu gmail.send (tidak diaktifkan default).
            "scope": "https://www.googleapis.com/auth/gmail.modify https://www.googleapis.com/auth/userinfo.email openid",
            "access_type": "offline",
            "prompt": "consent",
            "state": state,
        }
        url = "https://accounts.google.com/o/oauth2/v2/auth?" + main.urllib.parse.urlencode(params)
        return {
            "auth_url": url,
            "redirect_uri": redirect_uri,
            "note": "Pastikan redirect_uri ini di-whitelist persis di Google Cloud Console (OAuth Client)",
        }

    @router.get("/integrations/gmail/callback", include_in_schema=False)
    async def gmail_oauth_callback(
        code: str | None = None,
        state: str | None = None,
    ):
        if not code or not state:
            raise main.HTTPException(400, "Missing code/state")

        pool = await main.get_pool_safe()
        org_id: str | None = None
        redirect_uri: str | None = None

        # Prefer DB state store
        if pool:
            try:
                org_id, redirect_uri = await main.db_pop_oauth_state(pool, provider="gmail", state=state)
            except Exception:
                org_id, redirect_uri = None, None

        # Fallback lama: scan file integrations.json
        if not org_id:
            store_path = main.Path("data/integrations.json")
            data = {}
            try:
                if store_path.exists():
                    data = main.json.loads(store_path.read_text(encoding="utf-8") or "{}")
            except Exception:
                data = {}
            for k, v in (data or {}).items():
                oauth = v.get("gmail_oauth") or {}
                if oauth.get("state") == state:
                    org_id = k
                    redirect_uri = oauth.get("redirect_uri")
                    break

        if not org_id:
            raise main.HTTPException(400, "State tidak valid/expired")
        if not redirect_uri:
            redirect_uri = main.cfg.gmail_redirect_uri

        async with main.httpx.AsyncClient(timeout=15) as client:
            token_res = await client.post(
                "https://oauth2.googleapis.com/token",
                data={
                    "code": code,
                    "client_id": main.cfg.gmail_client_id,
                    "client_secret": main.cfg.gmail_client_secret,
                    "redirect_uri": redirect_uri,
                    "grant_type": "authorization_code",
                },
                headers={"Content-Type": "application/x-www-form-urlencoded"},
            )
            if token_res.status_code >= 400:
                raise main.HTTPException(400, f"Gmail token exchange gagal: {token_res.text[:200]}")
            tok = token_res.json()

        gmail = {
            "access_token": tok.get("access_token", ""),
            "refresh_token": tok.get("refresh_token", ""),
            "expires_in": tok.get("expires_in"),
            "token_type": tok.get("token_type"),
            "updated_at": main.datetime.now(main.timezone.utc).isoformat(),
        }

        # Try fetch connected email (optional, best-effort)
        try:
            async with main.httpx.AsyncClient(timeout=15) as client:
                u = await client.get(
                    "https://www.googleapis.com/oauth2/v2/userinfo",
                    headers={"Authorization": f"Bearer {gmail['access_token']}"},
                )
                if u.status_code < 400:
                    gmail["email"] = (u.json() or {}).get("email")
        except Exception:
            pass
        # Store Gmail tokens encrypted in DB (fallback: file store)
        await main._set_integration_auto(pool, org_id, "gmail", gmail)
        try:
            await main._clear_integration_auto(pool, org_id, "gmail_oauth")
        except Exception:
            pass

        # Redirect balik ke dashboard settings
        return main.RedirectResponse(url="/dashboard#settings")

    @router.post("/integrations/gmail/map-bot")
    async def gmail_map_bot(
        body: main.GmailMapBotReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        bot = await pool.fetchrow(
            "SELECT id FROM bots WHERE id=$1 AND org_id=$2",
            body.bot_id, user["org_id"],
        )
        if not bot:
            raise main.HTTPException(404, "Bot tidak ditemukan untuk org ini")

        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        gmail = dict(integ.get("gmail") or {})
        if not (gmail.get("refresh_token") or gmail.get("access_token")):
            raise main.HTTPException(400, "Gmail belum connected")

        gmail["bot_id"] = str(body.bot_id)
        gmail["updated_at"] = main.datetime.now(main.timezone.utc).isoformat()
        await main._set_integration_auto(pool, str(user["org_id"]), "gmail", gmail)
        return {"message": "Mapping Gmail -> bot tersimpan", "bot_id": gmail["bot_id"]}

    @router.post("/integrations/gmail/poll")
    async def gmail_poll(
        body: main.GmailPollReq,
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        gmail = dict(integ.get("gmail") or {})
        bot_id = (gmail.get("bot_id") or "").strip()
        if not bot_id:
            raise main.HTTPException(400, "Gmail belum di-map ke bot. Set dulu via /integrations/gmail/map-bot.")

        # validate bot belongs to org
        bot = await pool.fetchrow("SELECT id FROM bots WHERE id=$1 AND org_id=$2", bot_id, user["org_id"])
        if not bot:
            raise main.HTTPException(404, "Bot mapping tidak valid")

        access_token = (gmail.get("access_token") or "").strip()
        refresh_token = (gmail.get("refresh_token") or "").strip()
        if not (access_token or refresh_token):
            raise main.HTTPException(400, "Gmail token tidak ada. Connect ulang Gmail.")

        token = await main._gmail_get_access_token(access_token, refresh_token)
        msgs = await main._gmail_list_unread(token, max_results=max(1, min(20, body.max_messages)))

        processed = 0
        for mid in msgs:
            m = await main._gmail_get_message(token, mid)
            snippet = (m.get("snippet") or "").strip()
            headers = {h.get("name","").lower(): h.get("value","") for h in (m.get("payload", {}).get("headers") or [])}
            subject = headers.get("subject","").strip()
            from_h = headers.get("from","").strip()

            text = "Email masuk:\n"
            if subject:
                text += f"Subjek: {subject}\n"
            if from_h:
                text += f"Dari: {from_h}\n"
            if snippet:
                text += f"Ringkas: {snippet}\n"

            session_id = str(main.uuid.uuid5(main.uuid.NAMESPACE_URL, f"gmail:{user['org_id']}:{from_h}"))
            req = main.ChatReq(
                message=text.strip(),
                session_id=session_id,
                user_meta={"userId": f"gmail:{from_h}", "channel": "gmail", "gmail_message_id": mid},
            )
            await main.chat(bot_id=bot_id, body=req, pool=pool)
            processed += 1

            if body.mark_read:
                try:
                    await main._gmail_mark_read(token, mid)
                except Exception:
                    pass

        return {"processed": processed, "unread": len(msgs)}

    @router.get("/integrations/gmail/poller")
    async def gmail_poller_status(user=main.Depends(main.get_current_user)):
        return {
            "enabled": bool(main.cfg.gmail_poll_enabled),
            "interval_seconds": int(main.cfg.gmail_poll_interval_seconds or 60),
            "max_messages": int(main.cfg.gmail_poll_max_messages or 5),
            "mark_read": bool(main.cfg.gmail_poll_mark_read),
            "running": bool(main._gmail_poll_task is not None and not main._gmail_poll_task.done()),
        }

    @router.post("/integrations/gmail/poller/run-once")
    async def gmail_poller_run_once(
        user=main.Depends(main.get_current_user),
        pool=main.Depends(main.get_pool),
    ):
        """
        Trigger sekali untuk org ini (mirip poll, tapi pakai config server).
        """
        integ = await main._get_integrations_auto(pool, str(user["org_id"]))
        gmail = dict(integ.get("gmail") or {})
        bot_id = (gmail.get("bot_id") or "").strip()
        if not bot_id:
            raise main.HTTPException(400, "Gmail belum di-map ke bot.")

        access_token = (gmail.get("access_token") or "").strip()
        refresh_token = (gmail.get("refresh_token") or "").strip()
        if not (access_token or refresh_token):
            raise main.HTTPException(400, "Gmail token tidak ada. Connect ulang Gmail.")

        token = await main._gmail_get_access_token(access_token, refresh_token)
        msgs = await main._gmail_list_unread(token, max_results=max(1, min(20, int(main.cfg.gmail_poll_max_messages or 5))))

        processed = 0
        for mid in msgs:
            m = await main._gmail_get_message(token, mid)
            snippet = (m.get("snippet") or "").strip()
            headers = {h.get("name","").lower(): h.get("value","") for h in (m.get("payload", {}).get("headers") or [])}
            subject = headers.get("subject","").strip()
            from_h = headers.get("from","").strip()

            text = "Email masuk:\n"
            if subject:
                text += f"Subjek: {subject}\n"
            if from_h:
                text += f"Dari: {from_h}\n"
            if snippet:
                text += f"Ringkas: {snippet}\n"

            session_id = str(main.uuid.uuid5(main.uuid.NAMESPACE_URL, f"gmail:{user['org_id']}:{from_h}"))
            req = main.ChatReq(
                message=text.strip(),
                session_id=session_id,
                user_meta={"userId": f"gmail:{from_h}", "channel": "gmail", "gmail_message_id": mid},
            )
            await main.chat(bot_id=bot_id, body=req, pool=pool)
            processed += 1
            if bool(main.cfg.gmail_poll_mark_read):
                try:
                    await main._gmail_mark_read(token, mid)
                except Exception:
                    pass

        return {"processed": processed, "unread": len(msgs)}

    @router.get("/webhooks/meta", include_in_schema=False)
    async def meta_webhook_verify(request: main.Request):
        # Meta verification: hub.mode, hub.verify_token, hub.challenge
        qp = request.query_params
        mode = qp.get("hub.mode")
        token = qp.get("hub.verify_token")
        challenge = qp.get("hub.challenge")
        if mode == "subscribe" and token and token == main.cfg.meta_verify_token:
            return int(challenge) if challenge is not None else 0
        raise main.HTTPException(403, "Verification failed")

    @router.post("/webhooks/meta", include_in_schema=False)
    async def meta_webhook_receive(request: main.Request):
        body_bytes = await request.body()

        # X-Hub-Signature-256 (HMAC-SHA256) WAJIB diverifikasi -- sebelumnya cek
        # ini di-skip total kalau META_APP_SECRET kosong (fail-open: siapa pun
        # bisa POST payload palsu dan memicu auto-reply WhatsApp/FB/IG atas nama
        # tenant manapun yang ke-resolve dari payload). Tanpa secret terkonfigurasi,
        # tolak semua request -- operator harus isi META_APP_SECRET dulu sebelum
        # channel Meta benar-benar live, bukan diam-diam menerima tanpa autentikasi.
        app_secret = (main.cfg.meta_app_secret or "").strip()
        if not app_secret:
            main.logger.error("META_APP_SECRET belum dikonfigurasi -- webhook Meta ditolak (fail-closed).")
            raise main.HTTPException(503, "Meta webhook belum dikonfigurasi di server ini")
        sig = (request.headers.get("X-Hub-Signature-256") or "").strip()
        expected = "sha256=" + main.hmac.new(app_secret.encode("utf-8"), body_bytes, main.hashlib.sha256).hexdigest()
        if not (sig and main.hmac.compare_digest(sig, expected)):
            raise main.HTTPException(403, "Invalid signature")

        try:
            payload = main.json.loads(body_bytes.decode("utf-8") or "{}")
        except Exception:
            payload = {}

        # ── Diagnostic logging: lihat SETIAP webhook yang masuk ──
        _obj = str(payload.get("object") or "")
        _entries = payload.get("entry") or []
        main.logger.debug("=== WEBHOOK RECEIVED === object=%s entries=%d sig=%s", _obj, len(_entries), sig[:24] if sig else "NONE")
        for _i, _e in enumerate(_entries):
            _eid = str((_e or {}).get("id") or "")
            _msg = _e.get("messaging") or []
            _changes = _e.get("changes") or []
            if _msg:
                for _m in _msg:
                    _sender = ((_m.get("sender") or {}).get("id") or "")
                    _recipient = ((_m.get("recipient") or {}).get("id") or "")
                    _text = str(((_m.get("message") or {}).get("text") or "")).strip()
                    main.logger.debug("  entry[%d] id=%s | messaging sender=%s recipient=%s text=%r",
                                _i, _eid, _sender, _recipient, _text[:80])
            elif _changes:
                for _ch in _changes:
                    _field = _ch.get("field") or ""
                    _val = _ch.get("value") or {}
                    main.logger.debug("  entry[%d] id=%s | change field=%s phone=%s",
                                _i, _eid, _field, ((_val.get("metadata") or {}).get("phone_number_id") or ""))
            else:
                main.logger.debug("  entry[%d] id=%s | (no messaging/changes)", _i, _eid)

        # Best-effort log payload.
        try:
            p = main.Path("data/meta_webhooks.log")
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_text((p.read_text(encoding="utf-8") if p.exists() else "") + main.json.dumps(payload, ensure_ascii=False) + "\n", encoding="utf-8")
        except Exception:
            pass

        # Auto-reply WhatsApp inbound (basic):
        # - detect message text
        # - map phone_number_id -> bot_id
        # - call /chat pipeline and send response via WhatsApp Cloud API
        try:
            await main._handle_meta_whatsapp_inbound(payload)
            await main._handle_meta_social_inbound(payload)
        except Exception:
            # jangan bikin webhook gagal
            main.logger.exception("Meta webhook processing failed")

        return {"status": "ok"}

    return router
