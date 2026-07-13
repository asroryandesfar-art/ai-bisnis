"""Image + document generation routes, extracted from main.py.

The heavy helpers (_run_image_generation and its provider/moderation/queue web,
_check_media_cooldown, _media_signed_url) STAY in main and are injected here, so
the image tests that call main._run_image_generation directly and monkeypatch
main._replicate_image_queue / _moderate_prompt / cfg are unaffected. The media
file server (/media/{path}) and the signing helpers stay in main too.
"""
import hmac
from typing import Awaitable, Callable

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

import document_generator
import storage_backend
import vision_engine
from base import parse_json_response


class ImageGenerateReq(BaseModel):
    prompt: str = Field(min_length=3, max_length=2000)
    style: str = ""
    size: str = "1024x1024"
    quality: str = "medium"
    provider: str = ""  # kosong = pakai IMAGE_PROVIDER default dari .env
    bot_id: str | None = None
    conversation_id: str | None = None


class DocumentGenerateReq(BaseModel):
    format: str = Field(pattern="^(pdf|docx|xlsx|pptx)$")
    prompt: str = Field(min_length=3, max_length=2000)
    bot_id: str | None = None


_IMAGE_ANALYZE_ALLOWED_TYPES = {"image/png", "image/jpeg", "image/jpg", "image/webp", "image/gif"}
_IMAGE_ANALYZE_MAX_BYTES = 10 * 1024 * 1024


def build_media_router(
    *,
    get_current_user: Callable[..., Awaitable[dict]],
    get_pool: Callable[..., Awaitable],
    cfg,
    logger,
    check_media_cooldown: Callable[[str, str], int],
    run_image_generation: Callable[..., Awaitable[dict]],
    media_signed_url: Callable[[str], str],
    MediaImageReq,
    media_dir,
    sign_media_rel: Callable[[str], str],
) -> APIRouter:
    router = APIRouter()

    @router.get("/media/{path:path}", include_in_schema=False)
    async def serve_media(path: str, sig: str | None = None):
        p = (media_dir / path).resolve()
        # L-03: pakai is_relative_to (bukan startswith string) agar direktori
        # sibling berprefix sama (mis. data/media-rahasia) tidak lolos.
        if not p.is_relative_to(media_dir) or not p.exists() or not p.is_file():
            raise HTTPException(404, "Not found")
        # M-02: bila enforcement aktif, wajib tanda tangan sah (cegah akses lintas-
        # tenant via URL tebakan). Default (flag off) tetap melayani URL lama.
        if cfg.media_require_signature:
            expected = sign_media_rel(path)
            if not (sig and hmac.compare_digest(sig, expected)):
                raise HTTPException(403, "Tautan media tidak sah atau kedaluwarsa.")
        return FileResponse(p)

    @router.post("/media/image")
    async def generate_image(
        body: MediaImageReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        """Legacy endpoint (dipertahankan untuk kompatibilitas). Selalu pakai provider Replicate,
        sama seperti sebelumnya — logika baru ada di `/api/images/generate` (multi-provider)."""
        retry_after = check_media_cooldown(str(user["id"]), "image")
        if retry_after > 0:
            raise HTTPException(
                429,
                f"Tunggu {retry_after} detik sebelum generate gambar lagi.",
                headers={"Retry-After": str(retry_after)},
            )
        result = await run_image_generation(
            org_id=user["org_id"], user_id=str(user["id"]), pool=pool, prompt=body.prompt,
            provider_name="replicate", size=body.size, quality=body.quality,
        )
        return {"type": "image", "url": result["image_url"]}

    @router.post("/api/images/generate")
    async def api_generate_image(
        body: ImageGenerateReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        retry_after = check_media_cooldown(str(user["id"]), "image")
        if retry_after > 0:
            raise HTTPException(
                429,
                f"Tunggu {retry_after} detik sebelum generate gambar lagi.",
                headers={"Retry-After": str(retry_after)},
            )
        result = await run_image_generation(
            org_id=user["org_id"], user_id=str(user["id"]), pool=pool, prompt=body.prompt,
            provider_name=body.provider, size=body.size, style=body.style, quality=body.quality,
            bot_id=body.bot_id, conversation_id=body.conversation_id,
        )
        return {
            "image_url": result["image_url"],
            "provider": result["provider"],
            "generation_time": result["generation_time"],
        }

    @router.get("/api/images/history")
    async def api_image_history(
        user=Depends(get_current_user),
        pool=Depends(get_pool),
        bot_id: str | None = None,
        limit: int = 30,
        offset: int = 0,
    ):
        limit = max(1, min(int(limit or 30), 100))
        offset = max(0, int(offset or 0))
        if bot_id:
            rows = await pool.fetch(
                """SELECT id, bot_id, conversation_id, kind, provider, model, prompt, image_url,
                          size, style, status, estimated_cost, created_at
                   FROM image_generations WHERE org_id=$1 AND bot_id=$2
                   ORDER BY created_at DESC LIMIT $3 OFFSET $4""",
                user["org_id"], bot_id, limit, offset,
            )
        else:
            rows = await pool.fetch(
                """SELECT id, bot_id, conversation_id, kind, provider, model, prompt, image_url,
                          size, style, status, estimated_cost, created_at
                   FROM image_generations WHERE org_id=$1
                   ORDER BY created_at DESC LIMIT $2 OFFSET $3""",
                user["org_id"], limit, offset,
            )
        items = []
        for r in rows:
            item = dict(r)
            # M-02: tandatangani URL media saat dikirim ke klien (DB tetap simpan
            # path kanonik tanpa sig).
            item["image_url"] = media_signed_url(item.get("image_url"))
            items.append(item)
        return {"items": items}

    @router.post("/api/images/analyze")
    async def api_analyze_image(
        file: UploadFile = File(...),
        question: str = "",
        mode: str = "describe",
        bot_id: str | None = None,
        conversation_id: str | None = None,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        retry_after = check_media_cooldown(str(user["id"]), "image_analyze")
        if retry_after > 0:
            raise HTTPException(
                429,
                f"Tunggu {retry_after} detik sebelum analisis gambar lagi.",
                headers={"Retry-After": str(retry_after)},
            )

        content_type = (file.content_type or "").lower().split(";", 1)[0].strip()
        if content_type and content_type not in _IMAGE_ANALYZE_ALLOWED_TYPES:
            raise HTTPException(415, f"Format gambar tidak didukung: {content_type}")

        data = await file.read(_IMAGE_ANALYZE_MAX_BYTES + 1)
        if not data:
            raise HTTPException(400, "Gambar kosong.")
        if len(data) > _IMAGE_ANALYZE_MAX_BYTES:
            raise HTTPException(413, "Gambar maksimal 10 MB.")

        mode = (mode or "describe").strip().lower()
        if mode not in vision_engine.MODE_PROMPTS:
            mode = "describe"

        try:
            answer = await vision_engine.analyze_image(
                data, content_type or "image/png",
                api_key=cfg.groq_api_key, model=cfg.groq_model,
                question=question, mode=mode,
            )
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"Vision AI gagal: HTTP {exc.response.status_code}") from exc
        except Exception as exc:
            raise HTTPException(502, f"Vision AI gagal: {exc}") from exc

        try:
            await pool.execute(
                """INSERT INTO image_generations
                       (org_id, bot_id, conversation_id, user_id, kind, provider, model,
                        prompt, image_url, status)
                   VALUES ($1,$2,$3,$4,'analyze','vision',$5,$6,NULL,'completed')""",
                str(user["org_id"]), bot_id, conversation_id, str(user["id"]), cfg.groq_model,
                (question or mode),
            )
        except Exception:
            logger.warning("Gagal mencatat image_generations (analyze)", exc_info=True)

        return {"answer": answer, "mode": mode, "model": cfg.groq_model}

    @router.post("/api/documents/generate")
    async def api_generate_document(
        body: DocumentGenerateReq,
        user=Depends(get_current_user),
        pool=Depends(get_pool),
    ):
        retry_after = check_media_cooldown(str(user["id"]), "document")
        if retry_after > 0:
            raise HTTPException(
                429,
                f"Tunggu {retry_after} detik sebelum generate dokumen lagi.",
                headers={"Retry-After": str(retry_after)},
            )
        if not cfg.groq_api_key:
            raise HTTPException(503, "GROQ_API_KEY belum dikonfigurasi.")

        outline_prompt = (
            "Ubah permintaan berikut menjadi outline dokumen dalam format JSON dengan struktur:\n"
            '{"title": str, "sections": [{"heading": str, "body": str}], '
            '"table_rows": [[str, ...]], "slides": [{"title": str, "bullets": [str]}]}\n'
            "Isi table_rows hanya jika permintaan berbentuk data tabular (laporan, daftar angka). "
            "Isi slides hanya jika formatnya presentasi. Jawab dalam Bahasa Indonesia, dan jawab dalam format JSON.\n\n"
            f"Permintaan user: {body.prompt}"
        )
        headers = {"Authorization": f"Bearer {cfg.groq_api_key}", "Content-Type": "application/json"}
        payload = {
            "model": cfg.groq_model,
            "messages": [{"role": "user", "content": outline_prompt}],
            "temperature": 0.3,
            "max_tokens": 2048,
            "response_format": {"type": "json_object"},
        }
        try:
            async with httpx.AsyncClient(timeout=60) as client:
                resp = await client.post(
                    f"{cfg.groq_base_url.rstrip('/')}/chat/completions", json=payload, headers=headers,
                )
            resp.raise_for_status()
            choices = (resp.json() or {}).get("choices") or []
            raw = str((choices[0].get("message") or {}).get("content") or "") if choices else ""
            spec = parse_json_response(raw, default={})
        except Exception as exc:
            logger.warning("Gagal membuat outline dokumen: %s", exc)
            spec = {}

        spec = document_generator.normalize_spec(spec, fallback_title=body.prompt[:80])
        try:
            file_bytes, _content_type = document_generator.generate_document(body.format, spec)
        except ValueError as exc:
            raise HTTPException(400, str(exc))

        _, url = storage_backend.save_bytes("documents", file_bytes, ext=f".{body.format}")
        try:
            await pool.execute(
                """INSERT INTO generated_documents (org_id, bot_id, user_id, format, title, prompt, file_url, status)
                   VALUES ($1,$2,$3,$4,$5,$6,$7,'completed')""",
                str(user["org_id"]), body.bot_id, str(user["id"]), body.format, spec["title"], body.prompt, url,
            )
        except Exception:
            logger.warning("Gagal mencatat generated_documents", exc_info=True)

        return {"file_url": media_signed_url(url), "format": body.format, "title": spec["title"]}

    return router
