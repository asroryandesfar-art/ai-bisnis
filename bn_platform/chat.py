"""Core chat endpoint (/chat/{bot_id}), extracted from main.py.

The handler references ~30 main-level helpers/globals (many set lazily at
startup or monkeypatched by tests), so it uses them via `main.X` (late
binding) rather than a wide DI list. The chat decomposition helpers stay in
main, which re-exports this handler as `main.chat` (webhook routing + tests
depend on that name).
"""
import main
from fastapi import APIRouter


def build_chat_router() -> APIRouter:
    router = APIRouter()

    @router.post("/chat/{bot_id}")
    async def chat(
        bot_id: str,
        body:   main.ChatReq,
        request: main.Request,
        pool=main.Depends(main.get_pool),
    ):
        """
        Core chat endpoint — dipanggil oleh iframe widget.
        Public (tidak butuh user auth), tapi divalidasi via bot_id.
        """
        # 1. Load bot config
        bot = await pool.fetchrow(
            """SELECT b.id, b.org_id, b.system_prompt, b.language, b.temperature, b.reasoning_mode,
                      b.computer_agent_enabled,
                      o.plan, o.billing_status, o.conv_limit
               FROM bots b
               JOIN organizations o ON o.id = b.org_id
               WHERE b.id=$1 AND b.status IN ('active','training')""",
            bot_id,
        )
        if not bot:
            raise main.HTTPException(404, "Bot tidak aktif")

        # Rate limit (endpoint public). H-02: kunci rate-limit DIAMBIL DARI SERVER
        # (IP anti-spoof via CF-Connecting-IP), BUKAN dari user_meta.userId yang
        # dikontrol klien -- sebelumnya attacker cukup merotasi `userId` tiap
        # request untuk melewati limit per-user dan menguras kuota/biaya AI tenant.
        # user_meta tetap dipakai untuk identitas percakapan/memory, bukan limit.
        user_meta = body.user_meta or {}
        internal_channel = str(user_meta.get("_channel") or user_meta.get("channel") or "widget")
        safe_user_meta = {key: value for key, value in user_meta.items() if key not in {"channel", "_channel"}}
        rl_user_key = main._rate_limit_client_key(request)
        try:
            rl = await main._rate_limiter.check(
                user_id=rl_user_key,
                bot_id=str(bot_id),
                org_id=str(bot["org_id"]),
                plan=str(bot["plan"] or "starter"),
                agent="supervisor",
            )
            if rl.status == main.LimitStatus.BLOCKED:
                raise main.HTTPException(
                    status_code=429,
                    detail=rl.message or "Terlalu banyak request. Coba lagi nanti.",
                    headers={"Retry-After": str(rl.retry_after_s)},
                )
            if rl.status == main.LimitStatus.THROTTLED and rl.retry_after_s:
                await main.asyncio.sleep(min(2, rl.retry_after_s))
        except main.HTTPException:
            raise
        except Exception:
            # Jangan sampai rate limiter crash chat -- tapi tetap log supaya
            # operator tahu rate limiting diam-diam tidak aktif untuk request ini,
            # bukan cuma "tidak ada apa-apa" di log.
            main.logger.exception(
                "Rate limiter gagal, request dilanjutkan TANPA rate limiting org=%s bot=%s",
                bot["org_id"], bot_id,
            )

        # 2. Cek quota percakapan bulan ini (Phase 2: gunakan check_limit dari subscriptions/plans)
        if main._platform_check_limit:
            ok, detail = await main._platform_check_limit(pool, bot["org_id"], "conversations")
            if not ok:
                raise main.HTTPException(
                    429,
                    f"Limit percakapan/bulan paket '{detail['plan']}' tercapai "
                    f"({detail['used']}/{detail['limit']}). Upgrade di /api/billing/checkout.",
                )
        else:
            conv_this_month = await pool.fetchval(
                """SELECT COUNT(*) FROM conversations
                   WHERE org_id=$1 AND started_at >= DATE_TRUNC('month', NOW())""",
                bot["org_id"],
            )
            if conv_this_month >= bot["conv_limit"]:
                raise main.HTTPException(429, "Batas percakapan bulan ini tercapai. Upgrade plan.")

        # 3. Ambil atau buat conversation
        conv_id = body.session_id
        conv = None
        if conv_id:
            conv = await pool.fetchrow(
                "SELECT id, language FROM conversations WHERE id=$1 AND bot_id=$2", conv_id, bot_id
            )
            # Connector internal memakai UUID deterministik agar seluruh pesan user
            # dari channel yang sama tetap berada pada satu memory thread.
            if not conv and not user_meta.get("_channel"):
                conv_id = None

        is_new_conversation = not bool(conv)
        if not conv:
            conv_id = conv_id or str(main.uuid.uuid4())
            user_meta = body.user_meta or {}
            await pool.execute(
                """INSERT INTO conversations
                   (id, bot_id, org_id, end_user_id, end_user_name, end_user_email, end_user_meta, channel)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,$8)""",
                conv_id, bot_id, bot["org_id"],
                user_meta.get("userId"), user_meta.get("name") or user_meta.get("display_name"),
                user_meta.get("email"), main.json.dumps(safe_user_meta), internal_channel,
            )
            main.asyncio.create_task(main._dispatch_workflow_trigger(
                "new_customer",
                {
                    "conversation_id": conv_id, "bot_id": bot_id,
                    "end_user_id": user_meta.get("userId"), "end_user_name": user_meta.get("name"),
                    "end_user_email": user_meta.get("email"), "customer_type": "new",
                },
                org_id=str(bot["org_id"]), bot_id=bot_id,
            ))

        # 4. Simpan pesan user
        user_msg_id = str(main.uuid.uuid4())
        await pool.execute(
            "INSERT INTO messages (id, conversation_id, role, content) VALUES ($1,$2,'user',$3)",
            user_msg_id, conv_id, body.message,
        )

        # Percakapan yang sedang diambil alih manusia tidak boleh memanggil AI.
        try:
            active_handoff = await pool.fetchrow(
                """SELECT id, status FROM human_queue
                   WHERE conversation_id=$1 AND status IN ('waiting','assigned')""",
                conv_id,
            )
        except Exception:
            active_handoff = None
        if active_handoff:
            handoff_answer = (
                "Percakapan ini sedang ditangani oleh tim manusia kami. "
                "Pesan Anda sudah diteruskan dan agent akan membalas secepatnya."
            )
            await pool.execute(
                """INSERT INTO messages
                   (id, conversation_id, role, content, model, input_tokens, output_tokens, latency_ms)
                   VALUES ($1,$2,'assistant',$3,'system:human-handoff',0,0,0)""",
                str(main.uuid.uuid4()), conv_id, handoff_answer,
            )
            await pool.execute(
                "UPDATE conversations SET msg_count=msg_count+2, last_msg_at=NOW() WHERE id=$1",
                conv_id,
            )
            return {
                "answer": handoff_answer, "session_id": conv_id, "latency_ms": 0,
                "handoff": True, "handoff_status": str(active_handoff["status"]),
                "intent": "human_handoff", "selected_agent": "Human Handoff Agent",
                "confidence": None, "handoff_offered": True,
                "sources": [], "follow_up_questions": [],
            }

        # 4b. (OPT-IN) Routing lewat DeepSeek 3-otak. Default OFF -> lewati blok ini
        # dan pakai pipeline lama. Aktif hanya bila DEEPSEEK_BRAIN_ENABLED=1 dan ada
        # DEEPSEEK_API_KEY. Plan diambil dari DB (bot["plan"]) -> klien tak bisa paksa PRO.
        # Chat decomposition: opt-in DeepSeek-brain shortcut extracted to a helper.
        # Returns a full response dict when it handles the turn, or None to continue.
        brain_response = await main._maybe_deepseek_brain_answer(body.message, bot, bot_id, conv_id, pool)
        if brain_response is not None:
            return brain_response

        # 5. Ambil riwayat percakapan (max 10 pesan terakhir)
        history = await pool.fetch(
            """SELECT role, content FROM messages
               WHERE conversation_id=$1 ORDER BY created_at DESC LIMIT 10""",
            conv_id,
        )
        messages_for_llm = [
            {"role": r["role"], "content": r["content"]}
            for r in reversed(history)
        ]

        # 6. RAG: cari chunks relevan dari knowledge base
        _kb_started = main.time.perf_counter()
        relevant_chunks = await main._retrieve_chunks(pool, bot["org_id"], body.message, bot_id=bot_id)
        _kb_ms = (main.time.perf_counter() - _kb_started) * 1000
        main.logger.info(
            "kb_retrieval org_id=%s bot_id=%s conv_id=%s chunks=%s latency_ms=%.1f",
            bot["org_id"], bot_id, conv_id, len(relevant_chunks), _kb_ms,
        )
        if _kb_ms > main.KB_RETRIEVAL_LATENCY_BUDGET_MS:
            main.logger.warning(
                "Knowledge retrieval melebihi budget %sms: %.1fms (org_id=%s, bot_id=%s, conv_id=%s, chunks=%s)",
                main.KB_RETRIEVAL_LATENCY_BUDGET_MS, _kb_ms, bot["org_id"], bot_id, conv_id, len(relevant_chunks),
            )

        # 7. Resolve effective language and build system prompt
        effective_lang = main.language_middleware.resolve_language(
            user_message=body.message,
            agent_language=bot.get("language"),
            conversation_language=(conv.get("language") if conv else None),
        )
        await pool.execute(
            "UPDATE conversations SET language=$2 WHERE id=$1",
            conv_id, effective_lang,
        )
        system = main.language_middleware.build_system_prompt(
            bot["system_prompt"], relevant_chunks, effective_lang
        )
        # Chat decomposition: market-data augmentation extracted to a testable helper.
        system, market_answer = await main._build_market_augmentation(body.message, system, effective_lang)

        # Chat decomposition: real-time news augmentation extracted to a testable helper.
        system = await main._build_news_augmentation(body.message, system, effective_lang)

        # 7.5 Self-knowledge BotNesia: paket/usage/channel tenant + performa bisnis
        # (query DB ringan, tanpa LLM — selalu tersedia untuk semua mode/bot).
        # Chat decomposition: tenant self-knowledge + business context extracted.
        system, self_knowledge_context, business_context = await main._build_self_knowledge(pool, bot, bot_id, system)

        # 7.55 AI Workforce Phase 8 — Self Learning Company: insight yang sudah
        # di-approve manusia (lihat self_learning_engine.py) disuntik sebagai
        # konteks tambahan, no LLM di sini supaya tidak nambah latensi/biaya.
        try:
            from self_learning_engine import build_organizational_learning_context
            learning_context = await build_organizational_learning_context(pool, str(bot["org_id"]), bot_id)
        except Exception:
            learning_context = ""
        if learning_context:
            system = system + "\n\n" + learning_context

        # Chat decomposition: inline image generation extracted to a testable helper.
        system, chat_image_url, chat_image_provider = await main._maybe_generate_chat_image(
            message=body.message, bot=bot, bot_id=bot_id, conv_id=conv_id,
            user_meta=user_meta, effective_lang=effective_lang, system=system, pool=pool,
        )
        # 7.7 Chat + Computer Agent: deteksi & jalankan browsing (AI Agent Platform
        # Phase 3). Opt-in per bot (default FALSE -- bot lama tidak terpengaruh).
        # Aksi baca-saja auto-execute (mirip Chat+Image); aksi tulis (klik/isi
        # form/submit) TIDAK pernah auto-execute -- hanya disimpan sebagai task
        # pending_approval, dieksekusi nanti lewat endpoint approve setelah
        # disetujui staf tenant (lihat bn_platform/computer_agent.py).
        # Chat decomposition: computer-agent browsing extracted to a testable helper.
        system, chat_ca_screenshot_url = await main._maybe_run_computer_agent(
            bot=bot, message=body.message, bot_id=bot_id, conv_id=conv_id,
            user_meta=user_meta, effective_lang=effective_lang, system=system, pool=pool,
        )

        # 8. Panggil AI (Multi-Agent pipeline buatan kamu)
        t_start = main.time.monotonic()
        agent_meta: dict | None = None
        result = None
        should_handoff = False
        handoff_reason: str | None = None
        handoff_priority = "medium"
        intent_routing: dict = {}
        try:
            use_cloud = main.should_use_cloud(bot["plan"], bot["billing_status"])
            supervisor = main.get_supervisor(use_cloud)
            intelligence_context = {
                "bot_id": bot_id,
                "org_id": str(bot["org_id"]),
                "conversation_id": conv_id,
                "user_message": body.message,
                "messages": messages_for_llm,
                "knowledge_base_context": system,
                "resolved": False,
                "metadata": safe_user_meta,
                "reasoning_mode": bot["reasoning_mode"],
                "self_knowledge_context": self_knowledge_context,
                "business_context": business_context,
                "_observability_pool": pool,
                "_cheap_model": main.cfg.groq_cheap_model,
                "_strong_model": main.cfg.groq_model,
                "_search_api_key": main.cfg.search_api_key,
                "_searxng_url": main.cfg.searxng_url,
                "kb_chunks_count": len(relevant_chunks),
                "selected_language": effective_lang,
            }
            result = await supervisor.process(intelligence_context)
            answer = result.final_answer

            answer, result = await main._enforce_output_language(
                answer=answer, result=result, effective_lang=effective_lang, system=system,
                intelligence_context=intelligence_context, supervisor=supervisor,
                conv_id=conv_id, message=body.message,
            )

            # Shortcut data pasar mentah hanya untuk jalur cepat (standard). Mode Pro
            # sudah menganalisis data pasar via reasoning lens & sintesis jawaban —
            # jangan timpa dengan kutipan harga mentah.
            use_market_shortcut = bool(market_answer) and result.reasoning_mode_used != "pro"
            if use_market_shortcut:
                answer = market_answer
            if result.suggest_pro_mode:
                answer = (
                    answer.rstrip()
                    + "\n\nUntuk analisis lebih mendalam (alasan, konteks, dan kesimpulan) atas "
                      "pertanyaan seperti ini, aktifkan **Reasoning Mode: Pro** di pengaturan bot ini."
                )
            provider = "groq"
            model = result.routed_model or main.cfg.groq_model
            model_used = "system:market-data" if use_market_shortcut else f"multi-agent:cloud:{provider}:{model}"
            input_tokens = result.prompt_tokens
            output_tokens = result.completion_tokens
            latency_ms = result.total_latency_ms
            # Meta agent disimpan untuk logging internal, tidak dikirim ke frontend.
            agent_meta = main._build_agent_meta(result)

            intent_routing = result.intent_routing or {}
            if main._platform_evaluate_handoff:
                should_handoff, handoff_reason, handoff_priority = main._platform_evaluate_handoff(
                    allow_human_handoff=intent_routing.get("allow_human_handoff", False),
                    handoff_reason=intent_routing.get("reason") or result.escalation_reason,
                    escalation_urgency=result.escalation_urgency,
                    friction_points=result.friction_points,
                )
            else:
                should_handoff = bool(intent_routing.get("allow_human_handoff", False))
                handoff_reason = intent_routing.get("reason") or result.escalation_reason or "escalation_requested"
                handoff_priority = (result.escalation_urgency or "medium").lower()
            answer = await main._apply_handoff(
                should_handoff=should_handoff, result=result, answer=answer, pool=pool,
                bot=bot, bot_id=bot_id, conv_id=conv_id, handoff_reason=handoff_reason,
                handoff_priority=handoff_priority, user_meta=user_meta,
            )
        except Exception as e:
            main.logger.exception("CHAT EXCEPTION bot=%s conv=%s: %s", bot_id, conv_id, e)
            answer, model_used, input_tokens, output_tokens, latency_ms, agent_meta = await main._chat_error_fallback(
                exc=e, market_answer=market_answer, t_start=t_start, pool=pool,
                bot=bot, bot_id=bot_id, conv_id=conv_id, user_meta=user_meta,
            )

        # Additive routing fields dari Intent Router (backward-compatible di resp dict)
        return await main._persist_and_build_chat_response(
            pool=pool, bot=bot, bot_id=bot_id, conv_id=conv_id, message=body.message,
            answer=answer, model_used=model_used, input_tokens=input_tokens,
            output_tokens=output_tokens, latency_ms=latency_ms, result=result,
            intent_routing=intent_routing, should_handoff=should_handoff,
            handoff_reason=handoff_reason, relevant_chunks=relevant_chunks,
            agent_meta=agent_meta, intelligence_context=intelligence_context,
            is_new_conversation=is_new_conversation, user_meta=user_meta,
            chat_image_url=chat_image_url, chat_image_provider=chat_image_provider,
            chat_ca_screenshot_url=chat_ca_screenshot_url,
        )



    return router
