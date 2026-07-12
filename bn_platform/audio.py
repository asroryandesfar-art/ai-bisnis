"""Audio routes (TTS synthesize/speak/stop + Groq transcription), from main.py.

Self-contained: no shared media helpers, no platform hooks. Dependencies
injected (DI convention). Image/document/media-serving routes are intentionally
left in main — they share helpers (_run_image_generation, _media_signed_url,
_check_media_cooldown) with other endpoints and need a dedicated subsystem slice.
"""
import asyncio
import re
import sys
from typing import Awaitable, Callable

import httpx
from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile


def build_audio_router(
    *,
    get_current_user: Callable[..., Awaitable[dict]],
    cfg,
    logger,
    base_dir,
    SpeakAudioReq,
) -> APIRouter:
    router = APIRouter()

    @router.post("/audio/synthesize")
    async def synthesize_audio(
        body: SpeakAudioReq,
        user=Depends(get_current_user),
    ):
        from tts_engine import normalize_tts_text

        text = normalize_tts_text(body.text)
        if not text:
            raise HTTPException(400, "Teks suara kosong.")

        vendor_path = base_dir / ".tts_vendor"
        if str(vendor_path) not in sys.path:
            sys.path.insert(0, str(vendor_path))
        try:
            import edge_tts

            audio = bytearray()
            communicator = edge_tts.Communicate(
                text,
                voice="id-ID-GadisNeural",
                rate="+7%",
                volume="+6%",
                pitch="-1Hz",
                boundary="SentenceBoundary",
            )
            async for chunk in communicator.stream():
                if chunk.get("type") == "audio":
                    audio.extend(chunk.get("data") or b"")
            if not audio:
                raise RuntimeError("Provider tidak mengembalikan audio.")
            return Response(
                content=bytes(audio),
                media_type="audio/mpeg",
                headers={
                    "Cache-Control": "no-store",
                    "X-TTS-Voice": "id-ID-GadisNeural",
                    "X-TTS-Rate": "+7%",
                },
            )
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Neural TTS failed user=%s: %s", user["id"], exc)
            raise HTTPException(502, "Suara neural sedang tidak tersedia.") from exc

    @router.post("/audio/speak")
    async def speak_audio(
        body: SpeakAudioReq,
        user=Depends(get_current_user),
    ):
        text = re.sub(r"\s+", " ", body.text).strip()
        if not text:
            raise HTTPException(400, "Teks suara kosong.")

        try:
            process = await asyncio.create_subprocess_exec(
                "spd-say",
                "--wait",
                "--output-module", "espeak-ng",
                "--language", "id",
                "--voice-type", "female1",
                "--rate", "-8",
                "--pitch", "2",
                "--volume", "35",
                "--punctuation-mode", "some",
                text,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            timeout = max(20.0, min(120.0, len(text) / 8.0))
            _, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            if process.returncode != 0:
                detail = (stderr or b"").decode("utf-8", errors="ignore").strip()
                raise RuntimeError(detail or f"spd-say exit {process.returncode}")
            return {"status": "spoken", "characters": len(text)}
        except FileNotFoundError as exc:
            raise HTTPException(503, "Engine suara lokal tidak tersedia.") from exc
        except asyncio.TimeoutError as exc:
            try:
                process.kill()
            except Exception:
                pass
            raise HTTPException(504, "Pembacaan suara melewati batas waktu.") from exc
        except HTTPException:
            raise
        except Exception as exc:
            logger.warning("Local TTS failed user=%s: %s", user["id"], exc)
            raise HTTPException(502, "Engine suara lokal gagal membaca teks.") from exc

    @router.post("/audio/stop")
    async def stop_audio(user=Depends(get_current_user)):
        try:
            process = await asyncio.create_subprocess_exec(
                "spd-say", "--cancel",
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.DEVNULL,
            )
            await asyncio.wait_for(process.wait(), timeout=5)
        except Exception as exc:
            logger.debug("Stop local TTS failed user=%s: %s", user["id"], exc)
        return {"status": "stopped"}

    @router.post("/audio/transcribe")
    async def transcribe_audio(
        file: UploadFile = File(...),
        user=Depends(get_current_user),
    ):
        if not cfg.groq_api_key:
            raise HTTPException(503, "GROQ_API_KEY belum dikonfigurasi.")

        allowed_types = {
            "audio/webm", "audio/ogg", "audio/wav", "audio/x-wav",
            "audio/mpeg", "audio/mp4", "audio/x-m4a", "video/webm",
        }
        raw_content_type = (file.content_type or "").lower()
        content_type = raw_content_type.split(";", 1)[0].strip()
        if content_type and content_type not in allowed_types:
            raise HTTPException(415, f"Format audio tidak didukung: {content_type}")

        audio = await file.read(10 * 1024 * 1024 + 1)
        if not audio:
            raise HTTPException(400, "Rekaman audio kosong.")
        if len(audio) > 10 * 1024 * 1024:
            raise HTTPException(413, "Rekaman audio maksimal 10 MB.")

        filename = file.filename or "recording.webm"
        headers = {"Authorization": f"Bearer {cfg.groq_api_key}"}
        data = {
            "model": cfg.groq_whisper_model,
            "language": "id",
            "response_format": "json",
            "temperature": "0",
        }
        files = {"file": (filename, audio, content_type or "audio/webm")}
        try:
            async with httpx.AsyncClient(timeout=45) as client:
                response = await client.post(
                    f"{cfg.groq_base_url.rstrip('/')}/audio/transcriptions",
                    headers=headers,
                    data=data,
                    files=files,
                )
            if response.status_code == 401:
                raise HTTPException(503, "GROQ_API_KEY tidak valid.")
            if response.status_code == 429:
                raise HTTPException(429, "Layanan transkripsi sedang sibuk. Coba lagi sebentar.")
            response.raise_for_status()
            payload = response.json()
            text = str(payload.get("text") or "").strip()
            if not text:
                raise HTTPException(422, "Ucapan tidak terdeteksi. Coba bicara lebih jelas.")
            logger.info("Audio transcription success user=%s bytes=%s", user["id"], len(audio))
            return {"text": text, "model": cfg.groq_whisper_model}
        except HTTPException:
            raise
        except httpx.HTTPStatusError as exc:
            logger.warning("Groq transcription rejected status=%s", exc.response.status_code)
            raise HTTPException(502, "Provider transkripsi menolak rekaman audio.") from exc
        except httpx.HTTPError as exc:
            logger.warning("Groq transcription connection failed: %s", exc)
            raise HTTPException(502, "Tidak dapat menghubungi layanan transkripsi.") from exc

    return router
