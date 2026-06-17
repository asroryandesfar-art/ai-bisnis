"""image_providers.py — abstraksi multi-provider untuk image generation.

Provider yang didukung: OpenAI Images, Google Imagen (Gemini API key, bukan
Vertex service-account), Replicate (membungkus media_gen.generate_image_replicate
yang sudah dipakai endpoint lama), Stability AI, dan Fal.ai.

Setiap provider mengecek API key sendiri lewat `.available` — kalau key belum
diisi di .env, `generate()` melempar `ImageProviderError` dengan pesan jelas
(bukan exception generik), mengikuti pola graceful-degradation yang sudah ada
di `web_search_agent.py`/`tool_registry.py`.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass
from pathlib import Path

import httpx


@dataclass
class ImageResult:
    data: bytes
    content_type: str
    provider: str
    model: str
    revised_prompt: str = ""


class ImageProviderError(RuntimeError):
    """Error yang pesannya aman ditampilkan langsung ke user (sudah Bahasa Indonesia)."""


# Estimasi biaya kasar per gambar (USD) — bukan harga resmi/real-time, hanya
# angka internal supaya cost_records punya estimated_cost yang masuk akal.
PRICE_PER_IMAGE_USD = {
    "openai": 0.04,
    "google_imagen": 0.03,
    "replicate": 0.0055,
    "stability": 0.03,
    "fal": 0.02,
}


def estimate_image_cost_usd(provider: str) -> float:
    return PRICE_PER_IMAGE_USD.get((provider or "").strip().lower(), 0.0)


def _size_to_dims(size: str) -> tuple[int, int]:
    try:
        w, h = (size or "1024x1024").lower().split("x", 1)
        return int(w), int(h)
    except Exception:
        return 1024, 1024


def _apply_style(prompt: str, style: str) -> str:
    style = (style or "").strip()
    return f"{prompt}. Style: {style}." if style else prompt


class BaseImageProvider:
    name = "base"

    def __init__(self, api_key: str = ""):
        self.api_key = (api_key or "").strip()

    @property
    def available(self) -> bool:
        return bool(self.api_key)

    async def generate(
        self, prompt: str, *, size: str = "1024x1024", style: str = "", quality: str = "medium",
    ) -> ImageResult:
        raise NotImplementedError


class OpenAIImageProvider(BaseImageProvider):
    name = "openai"
    model = "gpt-image-1"

    async def generate(self, prompt, *, size="1024x1024", style="", quality="medium"):
        if not self.available:
            raise ImageProviderError("OPENAI_API_KEY belum dikonfigurasi.")
        payload = {
            "model": self.model,
            "prompt": _apply_style(prompt, style),
            "size": size if size in {"1024x1024", "1536x1024", "1024x1536", "auto"} else "1024x1024",
            "quality": quality if quality in {"low", "medium", "high", "auto"} else "medium",
            "n": 1,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.openai.com/v1/images/generations",
                headers={"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 401:
                raise ImageProviderError("OPENAI_API_KEY tidak valid.")
            if resp.status_code == 429:
                raise ImageProviderError("OpenAI Images sedang rate limit. Coba lagi sebentar.")
            resp.raise_for_status()
            items = (resp.json() or {}).get("data") or []
        if not items:
            raise ImageProviderError("OpenAI tidak mengembalikan gambar.")
        item = items[0]
        b64 = item.get("b64_json")
        if b64:
            img_bytes = base64.b64decode(b64)
        elif item.get("url"):
            async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
                dl = await client.get(item["url"])
                dl.raise_for_status()
                img_bytes = dl.content
        else:
            raise ImageProviderError("OpenAI tidak mengembalikan data gambar.")
        return ImageResult(
            data=img_bytes, content_type="image/png", provider=self.name, model=self.model,
            revised_prompt=str(item.get("revised_prompt") or ""),
        )


class GoogleImagenProvider(BaseImageProvider):
    """Pakai Gemini API key (generativelanguage.googleapis.com), bukan Vertex AI service-account."""
    name = "google_imagen"
    model = "imagen-3.0-generate-002"

    async def generate(self, prompt, *, size="1024x1024", style="", quality="medium"):
        if not self.available:
            raise ImageProviderError("GOOGLE_API_KEY belum dikonfigurasi.")
        url = f"https://generativelanguage.googleapis.com/v1beta/models/{self.model}:predict?key={self.api_key}"
        payload = {"instances": [{"prompt": _apply_style(prompt, style)}], "parameters": {"sampleCount": 1}}
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code in (401, 403):
                raise ImageProviderError("GOOGLE_API_KEY tidak valid atau belum punya akses Imagen.")
            if resp.status_code == 429:
                raise ImageProviderError("Google Imagen sedang rate limit. Coba lagi sebentar.")
            resp.raise_for_status()
            predictions = (resp.json() or {}).get("predictions") or []
        if not predictions:
            raise ImageProviderError("Google Imagen tidak mengembalikan gambar.")
        b64 = predictions[0].get("bytesBase64Encoded")
        if not b64:
            raise ImageProviderError("Google Imagen tidak mengembalikan data gambar.")
        return ImageResult(data=base64.b64decode(b64), content_type="image/png", provider=self.name, model=self.model)


_STABILITY_ASPECT_RATIOS = {
    "1:1": 1.0, "16:9": 16 / 9, "21:9": 21 / 9, "2:3": 2 / 3,
    "3:2": 3 / 2, "4:5": 4 / 5, "5:4": 5 / 4, "9:16": 9 / 16, "9:21": 9 / 21,
}


def _closest_aspect_ratio(w: int, h: int) -> str:
    ratio = (w / h) if h else 1.0
    return min(_STABILITY_ASPECT_RATIOS.items(), key=lambda kv: abs(kv[1] - ratio))[0]


class StabilityImageProvider(BaseImageProvider):
    name = "stability"
    model = "stable-image-core"

    async def generate(self, prompt, *, size="1024x1024", style="", quality="medium"):
        if not self.available:
            raise ImageProviderError("STABILITY_API_KEY belum dikonfigurasi.")
        w, h = _size_to_dims(size)
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                "https://api.stability.ai/v2beta/stable-image/generate/core",
                headers={"Authorization": f"Bearer {self.api_key}", "Accept": "image/*"},
                data={
                    "prompt": _apply_style(prompt, style),
                    "output_format": "png",
                    "aspect_ratio": _closest_aspect_ratio(w, h),
                },
                files={"none": (None, b"")},
            )
            if resp.status_code == 401:
                raise ImageProviderError("STABILITY_API_KEY tidak valid.")
            if resp.status_code == 429:
                raise ImageProviderError("Stability AI sedang rate limit. Coba lagi sebentar.")
            resp.raise_for_status()
            img_bytes = resp.content
        if not img_bytes:
            raise ImageProviderError("Stability AI tidak mengembalikan gambar.")
        return ImageResult(data=img_bytes, content_type="image/png", provider=self.name, model=self.model)


class FalImageProvider(BaseImageProvider):
    name = "fal"
    model = "fal-ai/flux/dev"

    async def generate(self, prompt, *, size="1024x1024", style="", quality="medium"):
        if not self.available:
            raise ImageProviderError("FAL_API_KEY belum dikonfigurasi.")
        w, h = _size_to_dims(size)
        payload = {
            "prompt": _apply_style(prompt, style),
            "image_size": {"width": w, "height": h},
            "num_images": 1,
        }
        async with httpx.AsyncClient(timeout=90) as client:
            resp = await client.post(
                f"https://fal.run/{self.model}",
                headers={"Authorization": f"Key {self.api_key}", "Content-Type": "application/json"},
                json=payload,
            )
            if resp.status_code == 401:
                raise ImageProviderError("FAL_API_KEY tidak valid.")
            if resp.status_code == 429:
                raise ImageProviderError("Fal.ai sedang rate limit. Coba lagi sebentar.")
            resp.raise_for_status()
            images = (resp.json() or {}).get("images") or []
        if not images:
            raise ImageProviderError("Fal.ai tidak mengembalikan gambar.")
        img_url = images[0].get("url")
        if not img_url:
            raise ImageProviderError("Fal.ai tidak mengembalikan URL gambar.")
        async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
            dl = await client.get(img_url)
            dl.raise_for_status()
            img_bytes = dl.content
        return ImageResult(data=img_bytes, content_type="image/png", provider=self.name, model=self.model)


def _replicate_overrides_for_model(model: str | None, size: str, quality: str, base_overrides: dict | None) -> dict:
    """Override input per model Replicate tertentu yang butuh parameter non-standar."""
    overrides = dict(base_overrides or {})
    model_name = (model or "").strip().lower()
    quality_name = (quality or "medium").strip().lower()

    if "black-forest-labs/flux-2-pro" in model_name:
        aspect_map = {"1024x1024": "1:1", "1536x1024": "3:2", "1024x1536": "2:3"}
        if "aspect_ratio" not in overrides:
            overrides["aspect_ratio"] = aspect_map.get((size or "1024x1024").lower(), "1:1")
        overrides.setdefault("resolution", "1 MP")
        overrides.setdefault("output_format", "webp")
        if "output_quality" not in overrides:
            overrides["output_quality"] = {"low": 70, "medium": 80, "high": 90, "auto": 80}.get(quality_name, 80)
        overrides.setdefault("safety_tolerance", 2)
        overrides.setdefault("prompt_upsampling", False)
        overrides.pop("width", None)
        overrides.pop("height", None)
        return overrides

    if "width" not in overrides and "height" not in overrides:
        w, h = _size_to_dims(size)
        overrides["width"], overrides["height"] = w, h
    return overrides


class ReplicateImageProvider(BaseImageProvider):
    """Membungkus media_gen.generate_image_replicate — logika Replicate tidak diduplikasi."""
    name = "replicate"

    def __init__(self, tokens: list[str], version: str = "", model: str = "", input_overrides: dict | None = None):
        self.tokens = [t for t in (tokens or []) if t]
        self.version = (version or "").strip()
        self.model = (model or "").strip()
        self.input_overrides = dict(input_overrides or {})

    @property
    def available(self) -> bool:
        return bool(self.tokens and (self.version or self.model))

    async def generate(self, prompt, *, size="1024x1024", style="", quality="medium"):
        if not self.available:
            raise ImageProviderError("REPLICATE_API_TOKEN + REPLICATE_IMAGE_VERSION/MODEL belum dikonfigurasi.")
        from media_gen import generate_image_replicate

        models = [m.strip() for m in self.model.split(",") if m.strip()] if self.model else [None]
        out_dir = Path("data/media/generated").resolve()
        last_err: Exception | None = None
        for tok in self.tokens:
            for model_name in models:
                try:
                    overrides = _replicate_overrides_for_model(model_name, size, quality, self.input_overrides)
                    overrides.setdefault("num_outputs", 1)
                    path = await generate_image_replicate(
                        tok,
                        version=(self.version or None),
                        model=model_name,
                        prompt=_apply_style(prompt, style),
                        out_dir=out_dir,
                        input_overrides=overrides,
                        timeout_s=140.0,
                    )
                    content_type = "image/webp" if overrides.get("output_format") == "webp" else "image/png"
                    return ImageResult(
                        data=path.read_bytes(), content_type=content_type,
                        provider=self.name, model=model_name or self.version,
                    )
                except Exception as exc:
                    last_err = exc
                    continue
        raise ImageProviderError(f"Replicate gagal: {last_err}")


def get_provider(
    name: str,
    *,
    openai_api_key: str = "",
    google_api_key: str = "",
    stability_api_key: str = "",
    fal_api_key: str = "",
    replicate_tokens: list[str] | None = None,
    replicate_version: str = "",
    replicate_model: str = "",
    replicate_input_overrides: dict | None = None,
) -> BaseImageProvider:
    key = (name or "replicate").strip().lower()
    if key == "openai":
        return OpenAIImageProvider(openai_api_key)
    if key in ("google_imagen", "google", "imagen"):
        return GoogleImagenProvider(google_api_key)
    if key == "stability":
        return StabilityImageProvider(stability_api_key)
    if key == "fal":
        return FalImageProvider(fal_api_key)
    if key == "replicate":
        return ReplicateImageProvider(replicate_tokens or [], replicate_version, replicate_model, replicate_input_overrides)
    raise ImageProviderError(f"Provider gambar '{name}' tidak dikenal.")


_INDO_IMAGE_VERBS = r"(?:buat(?:kan)?|bikin(?:kan)?|desain(?:kan)?|gambar(?:kan)?|generate|create|hasilkan|rancang)"
_IMAGE_NOUNS = (
    r"(?:logo|ilustrasi|illustration|poster|gambar|image|banner|mascot|maskot|desain|design|"
    r"wallpaper|avatar|icon|ikon|thumbnail|cover|sketsa|sketch|lukisan|artwork|infografis|infographic)"
)
_IMAGE_REQUEST_RE = re.compile(rf"\b{_INDO_IMAGE_VERBS}\b.{{0,40}}\b{_IMAGE_NOUNS}\b", re.IGNORECASE)


def looks_like_image_request(text: str) -> bool:
    """Deteksi heuristik no-LLM: user minta gambar dibuat (bukan video/dokumen)."""
    t = (text or "").strip()
    if not t:
        return False
    return bool(_IMAGE_REQUEST_RE.search(t))
