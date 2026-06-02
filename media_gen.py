from __future__ import annotations

import asyncio
import logging
import random
import time
import urllib.parse
import uuid
from pathlib import Path

logger = logging.getLogger("botnesia.replicate")

_MODEL_DEFAULT_VERSION_CACHE: dict[tuple[str, str], str] = {}


class ReplicateRateLimitError(RuntimeError):
    def __init__(self, message: str, *, retry_after_s: float = 0.0):
        super().__init__(message)
        self.retry_after_s = max(0.0, float(retry_after_s or 0.0))


def ensure_dir(p: Path) -> None:
    p.mkdir(parents=True, exist_ok=True)


def _parse_retry_after(headers: object) -> float:
    if not headers:
        return 0.0
    try:
        value = headers.get("Retry-After") or headers.get("retry-after")  # type: ignore[attr-defined]
    except Exception:
        value = None
    if not value:
        return 0.0
    try:
        return max(0.0, float(value))
    except Exception:
        return 0.0


def _compute_backoff_delay(
    attempt: int,
    *,
    retry_after_s: float = 0.0,
    base_delay_s: float = 1.5,
    max_delay_s: float = 20.0,
) -> float:
    if retry_after_s > 0:
        return min(max_delay_s, retry_after_s + random.uniform(0.05, 0.35))
    delay = base_delay_s * (2 ** max(0, attempt - 1))
    return min(max_delay_s, delay + random.uniform(0.10, 0.50))


async def _replicate_request_with_retry(
    client,
    method: str,
    url: str,
    *,
    json_body: dict | None = None,
    max_retries: int = 5,
    base_delay_s: float = 1.5,
    max_delay_s: float = 20.0,
):
    import httpx

    last_err: Exception | None = None
    for attempt in range(1, max_retries + 1):
        try:
            response = await client.request(method, url, json=json_body)
            if response.status_code == 429:
                retry_after = _parse_retry_after(response.headers)
                if attempt >= max_retries:
                    raise ReplicateRateLimitError(
                        "Replicate sedang rate limit. Coba lagi beberapa saat.",
                        retry_after_s=retry_after,
                    )
                delay = _compute_backoff_delay(
                    attempt,
                    retry_after_s=retry_after,
                    base_delay_s=base_delay_s,
                    max_delay_s=max_delay_s,
                )
                logger.warning(
                    "Replicate 429 on %s %s (attempt %s/%s, retry_after=%.2fs, delay=%.2fs)",
                    method,
                    url,
                    attempt,
                    max_retries,
                    retry_after,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            response.raise_for_status()
            return response
        except ReplicateRateLimitError:
            raise
        except (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.RemoteProtocolError) as exc:
            last_err = exc
            if attempt >= max_retries:
                break
            delay = _compute_backoff_delay(
                attempt,
                base_delay_s=base_delay_s,
                max_delay_s=max_delay_s,
            )
            logger.warning(
                "Replicate transient error on %s %s (attempt %s/%s): %s; retry in %.2fs",
                method,
                url,
                attempt,
                max_retries,
                exc,
                delay,
            )
            await asyncio.sleep(delay)
        except httpx.HTTPStatusError as exc:
            last_err = exc
            code = exc.response.status_code if exc.response is not None else 0
            if code >= 500 and attempt < max_retries:
                delay = _compute_backoff_delay(
                    attempt,
                    base_delay_s=base_delay_s,
                    max_delay_s=max_delay_s,
                )
                logger.warning(
                    "Replicate %s on %s %s (attempt %s/%s); retry in %.2fs",
                    code,
                    method,
                    url,
                    attempt,
                    max_retries,
                    delay,
                )
                await asyncio.sleep(delay)
                continue
            raise

    if last_err is not None:
        raise last_err
    raise RuntimeError("Replicate request gagal tanpa detail error.")


async def _replicate_wait_prediction(
    api_token: str,
    prediction: dict,
    *,
    timeout_s: float = 120.0,
    poll_interval_s: float = 1.5,
) -> dict:
    """
    Wait until a Replicate prediction finishes. Returns final prediction JSON.
    """
    import httpx

    pred_id = (prediction or {}).get("id")
    if not pred_id:
        return prediction or {}

    url = f"https://api.replicate.com/v1/predictions/{pred_id}"
    headers = {"Authorization": f"Token {api_token}"}
    deadline = time.time() + float(timeout_s)

    async with httpx.AsyncClient(timeout=20, headers=headers) as client:
        while time.time() < deadline:
            r = await _replicate_request_with_retry(
                client,
                "GET",
                url,
                max_retries=5,
                base_delay_s=max(1.0, float(poll_interval_s)),
                max_delay_s=15.0,
            )
            p = r.json() or {}
            status = (p.get("status") or "").lower()
            logger.debug("Replicate prediction %s status=%s", pred_id, status or "unknown")
            if status in {"succeeded", "failed", "canceled"}:
                return p
            await asyncio.sleep(float(poll_interval_s))
    return prediction or {}


async def _replicate_get_default_version(api_token: str, model: str) -> str:
    import httpx

    key = (api_token, model)
    if key in _MODEL_DEFAULT_VERSION_CACHE:
        return _MODEL_DEFAULT_VERSION_CACHE[key]

    url = f"https://api.replicate.com/v1/models/{model}"
    headers = {"Authorization": f"Token {api_token}", "Content-Type": "application/json"}
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        r = await _replicate_request_with_retry(
            client,
            "GET",
            url,
            max_retries=5,
            base_delay_s=2.0,
            max_delay_s=25.0,
        )
        data = r.json() or {}
    # Replicate may return `default_version` as a string id or as an object.
    default_version = data.get("default_version")
    resolved: str | None = None
    if default_version:
        if isinstance(default_version, str):
            resolved = default_version
        elif isinstance(default_version, dict):
            # object containing the id field
            resolved = default_version.get("id") or default_version.get("version")

    # Fallback: pick the first entry from `versions` if available
    if not resolved:
        versions = data.get("versions") or []
        if isinstance(versions, list) and versions:
            first = versions[0]
            if isinstance(first, dict):
                resolved = first.get("id")

    if not resolved or not isinstance(resolved, str):
        raise RuntimeError(f"Replicate model {model} tidak punya default version")

    _MODEL_DEFAULT_VERSION_CACHE[key] = resolved
    return resolved


async def _replicate_create_prediction(
    api_token: str,
    *,
    version: str | None = None,
    model: str | None = None,
    input_data: dict,
) -> dict:
    import httpx

    url = "https://api.replicate.com/v1/predictions"
    headers = {"Authorization": f"Token {api_token}", "Content-Type": "application/json"}
    v = (version or "").strip()
    m = (model or "").strip()
    # Allow inline version in model string like 'owner/name@version-id'
    if m and "@" in m and not v:
        parts = m.split("@", 1)
        if parts and parts[1].strip():
            m = parts[0].strip()
            v = parts[1].strip()
    if not v and not m:
        raise ValueError("Replicate membutuhkan `version` atau `model`.")
    if not v and m:
        v = await _replicate_get_default_version(api_token, m)
        m = ""
    if v and m:
        # Prefer explicit version if both are set (avoid ambiguity).
        m = ""
    payload: dict = {"input": input_data}
    payload["version"] = v
    async with httpx.AsyncClient(timeout=30, headers=headers) as client:
        logger.debug(
            "Creating Replicate prediction using version=%s",
            v,
        )
        r = await _replicate_request_with_retry(
            client,
            "POST",
            url,
            json_body=payload,
            max_retries=5,
            base_delay_s=2.0,
            max_delay_s=25.0,
        )
        return r.json() or {}


async def _download_to_path(url: str, out_path: Path) -> Path:
    import httpx

    out_path.parent.mkdir(parents=True, exist_ok=True)
    async with httpx.AsyncClient(timeout=60, follow_redirects=True) as client:
        r = await client.get(url)
        r.raise_for_status()
        out_path.write_bytes(r.content)
    return out_path


async def generate_image_replicate(
    api_token: str,
    *,
    version: str | None = None,
    model: str | None = None,
    prompt: str,
    out_dir: Path,
    input_overrides: dict | None = None,
    timeout_s: float = 120.0,
) -> Path:
    """
    Generate an image using Replicate (requires REPLICATE_API_TOKEN + model version id).
    Returns path to the first generated image.
    """
    ensure_dir(out_dir)
    input_data = {"prompt": prompt}
    if isinstance(input_overrides, dict):
        input_data.update(input_overrides)
    pred = await _replicate_create_prediction(
        api_token,
        version=version,
        model=model,
        input_data=input_data,
    )
    final = await _replicate_wait_prediction(api_token, pred, timeout_s=timeout_s)
    if (final.get("status") or "").lower() != "succeeded":
        raise RuntimeError(f"Replicate gagal: {final.get('error') or final.get('status')}")

    output = final.get("output")
    url = None
    if isinstance(output, str):
        url = output
    elif isinstance(output, list) and output:
        url = output[0]
    if not url:
        raise RuntimeError("Replicate output URL tidak ditemukan")

    filename = f"img_{uuid.uuid4().hex}.png"
    return await _download_to_path(str(url), out_dir / filename)


async def generate_video_replicate(
    api_token: str,
    *,
    version: str | None = None,
    model: str | None = None,
    prompt: str,
    out_dir: Path,
    input_overrides: dict | None = None,
    timeout_s: float = 240.0,
) -> Path:
    """
    Generate a video using Replicate (text-to-video or image-to-video model).
    Expects output as a URL (mp4) or list of URLs.
    """
    ensure_dir(out_dir)
    input_data = {"prompt": prompt}
    if isinstance(input_overrides, dict):
        input_data.update(input_overrides)
    pred = await _replicate_create_prediction(
        api_token,
        version=version,
        model=model,
        input_data=input_data,
    )
    final = await _replicate_wait_prediction(api_token, pred, timeout_s=timeout_s)
    if (final.get("status") or "").lower() != "succeeded":
        raise RuntimeError(f"Replicate gagal: {final.get('error') or final.get('status')}")

    output = final.get("output")
    url = None
    if isinstance(output, str):
        url = output
    elif isinstance(output, list) and output:
        url = output[0]
    if not url:
        raise RuntimeError("Replicate output URL tidak ditemukan")

    filename = f"vid_{uuid.uuid4().hex}.mp4"
    return await _download_to_path(str(url), out_dir / filename)
