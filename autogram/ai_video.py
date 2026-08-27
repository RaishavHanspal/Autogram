"""
Optional AI image-to-video generation.

The AI video stage is deliberately optional.

If:
- no API key exists,
- provider is unavailable,
- credits are exhausted,
- generation times out,
- download fails,

the caller can fall back to the normal FFmpeg Reel renderer.

This module must NEVER make the entire Reel pipeline dependent
on an external video provider.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .config import Config
from .logging_utils import get_logger

log = get_logger("ai_video")


class AIVideoError(RuntimeError):
    """AI video generation failed."""


def _http_json(
    method: str,
    url: str,
    headers: dict[str, str],
    payload: dict[str, Any] | None = None,
    timeout: int = 30,
) -> tuple[int, dict[str, Any]]:
    """
    Small stdlib-only HTTP JSON client.

    Avoids adding another dependency to the CPU runner.
    """

    body: bytes | None = None

    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        headers = {
            **headers,
            "Content-Type": "application/json",
        }

    request = urllib.request.Request(
        url,
        data=body,
        headers=headers,
        method=method,
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            raw = response.read()

        if not raw:
            return response.status, {}

        return response.status, json.loads(raw.decode("utf-8"))

    except urllib.error.HTTPError as exc:
        err_body = exc.read().decode(
            "utf-8",
            "replace",
        )

        raise AIVideoError(f"HTTP {exc.code} from {url}: {err_body[-1000:]}") from exc

    except urllib.error.URLError as exc:
        raise AIVideoError(f"network error calling {url}: {exc}") from exc


def _download(
    url: str,
    destination: Path,
    timeout: int = 120,
) -> Path:
    destination.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Autogram/1.0",
        },
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=timeout,
        ) as response:
            data = response.read()

        if len(data) < 10_000:
            raise AIVideoError("downloaded AI video is suspiciously small")

        destination.write_bytes(data)

    except Exception as exc:
        raise AIVideoError(f"failed to download AI video: {exc}") from exc

    return destination


def _read_image_data_url(image_path: Path) -> str:
    """
    Convert a local image into a data URL.

    Used only when the provider supports image data URLs.
    """

    import base64
    import mimetypes

    mime = mimetypes.guess_type(str(image_path))[0] or "image/jpeg"

    encoded = base64.b64encode(image_path.read_bytes()).decode("ascii")

    return f"data:{mime};base64,{encoded}"


def _pixverse_prompt(
    scene_description: str,
) -> str:
    """
    Convert an Autogram scene into an image-to-video prompt.

    We explicitly request subtle movement because large movements
    frequently cause identity drift in image-to-video models.
    """

    return (
        "Cinematic romantic photography. "
        "Preserve the exact identity, facial features, "
        "hair, clothing and body proportions of every person "
        "from the reference image. "
        "Natural subtle human movement. "
        "Gentle eye movement, breathing, slight smile, "
        "small head movement and natural hair/clothing motion. "
        "Very subtle realistic camera movement. "
        "No morphing, no identity change, no extra people, "
        "no duplicated limbs, no face distortion. "
        "Photorealistic natural motion. "
        f"Scene context: {scene_description}"
    )


def _pixverse_generate(
    image_path: Path,
    prompt: str,
    cfg: Config,
    output_path: Path,
    image_url: str | None = None,
) -> Path:
    """
    PixVerse image-to-video implementation.

    NOTE:
    PixVerse API availability/credits are controlled by PixVerse.
    This function is therefore always wrapped by the fallback layer.
    """

    api_key = os.getenv("PIXVERSE_API_KEY")

    if not api_key:
        raise AIVideoError("PIXVERSE_API_KEY is not configured")

    base = "https://app-api.pixverse.ai"

    headers = {
        "API-KEY": api_key,
        "User-Agent": "Autogram/1.0",
        "Accept": "application/json",
    }

    # ---------------------------------------------------------------
    # Upload image
    # ---------------------------------------------------------------

    image_url = image_url or os.getenv("PIXVERSE_IMAGE_URL")

    if not image_url:
        raise AIVideoError("no public image URL (pass image_url or set PIXVERSE_IMAGE_URL)")

    status, upload = _http_json(
        "POST",
        f"{base}/openapi/v2/image/upload",
        headers,
        {
            "url": image_url,
        },
        timeout=30,
    )

    if status < 200 or status >= 300:
        raise AIVideoError(f"PixVerse image upload failed: {upload}")

    image_id = upload.get("Resp", {}).get("image_id") or upload.get("image_id")

    if not image_id:
        raise AIVideoError(f"PixVerse upload returned no image_id: {upload}")

    # ---------------------------------------------------------------
    # Create image-to-video task
    # ---------------------------------------------------------------

    payload = {
        "image_id": image_id,
        "prompt": prompt,
        "duration": cfg.reel.ai_video.duration_s,
        "model": os.getenv(
            "PIXVERSE_MODEL",
            "v5",
        ),
    }

    status, result = _http_json(
        "POST",
        f"{base}/openapi/v2/video/img/generate",
        headers,
        payload,
        timeout=60,
    )

    if status < 200 or status >= 300:
        raise AIVideoError(f"PixVerse generation request failed: {result}")

    task_id = (
        result.get("Resp", {}).get("video_id") or result.get("video_id") or result.get("task_id")
    )

    if not task_id:
        raise AIVideoError(f"PixVerse returned no task id: {result}")

    # ---------------------------------------------------------------
    # Poll
    # ---------------------------------------------------------------

    deadline = time.monotonic() + cfg.reel.ai_video.timeout_s

    while time.monotonic() < deadline:
        status, data = _http_json(
            "GET",
            f"{base}/openapi/v2/video/result/{task_id}",
            headers,
            timeout=30,
        )

        status_data = data.get("Resp", data)

        state = str(status_data.get("status") or status_data.get("state") or "").lower()

        log.info(
            "PixVerse task=%s status=%s",
            task_id,
            state or "unknown",
        )

        if state in {
            "completed",
            "success",
            "succeeded",
            "finished",
        }:
            video_url = (
                status_data.get("url")
                or status_data.get("video_url")
                or status_data.get("video", {}).get("url")
            )

            if not video_url:
                raise AIVideoError(f"PixVerse completed without video URL: {data}")

            return _download(
                video_url,
                output_path,
                timeout=120,
            )

        if state in {
            "failed",
            "error",
            "cancelled",
            "canceled",
        }:
            raise AIVideoError(f"PixVerse generation failed: {data}")

        time.sleep(
            max(
                2,
                cfg.reel.ai_video.poll_interval_s,
            )
        )

    raise AIVideoError(f"PixVerse generation timed out after {cfg.reel.ai_video.timeout_s}s")


def _huggingface_generate(
    image_path: Path,
    prompt: str,
    cfg: Config,
    output_path: Path,
) -> Path:
    """Hugging Face serverless image-to-video (free tier).

    Unlike PixVerse this needs no public image URL — the still is POSTed as raw
    bytes. Free serverless availability varies by model, and models cold-start
    (HTTP 503 with an estimated_time); we retry within the configured timeout.
    The whole call is wrapped by the fallback layer, so any failure just drops
    back to the FFmpeg reel.
    """
    token = os.getenv("HF_TOKEN") or os.getenv("HUGGINGFACEHUB_API_TOKEN")
    if not token:
        raise AIVideoError("HF_TOKEN is not configured")

    model = os.getenv("HF_VIDEO_MODEL", "stabilityai/stable-video-diffusion-img2vid-xt")
    url = f"https://api-inference.huggingface.co/models/{model}"
    data = image_path.read_bytes()
    headers = {
        "Authorization": f"Bearer {token}",
        "User-Agent": "Autogram/1.0",
        "Content-Type": "image/jpeg",
        "Accept": "video/mp4",
        # Some models read a text prompt from this header; ignored otherwise.
        "X-Prompt": prompt[:512],
    }

    poll = max(2, int(cfg.reel.ai_video.poll_interval_s))
    deadline = time.monotonic() + cfg.reel.ai_video.timeout_s

    while time.monotonic() < deadline:
        request = urllib.request.Request(url, data=data, headers=headers, method="POST")
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                content_type = response.headers.get("Content-Type", "")
                payload = response.read()
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code == 503:  # model loading — wait and retry
                log.info("HF model %s loading; retrying in %ds", model, poll)
                time.sleep(poll)
                continue
            raise AIVideoError(f"HF HTTP {exc.code} for {model}: {body[-500:]}") from exc
        except urllib.error.URLError as exc:
            raise AIVideoError(f"HF network error for {model}: {exc}") from exc

        if "video" in content_type or "octet-stream" in content_type:
            if len(payload) < 10_000:
                raise AIVideoError("HF returned a suspiciously small video")
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_bytes(payload)
            return output_path

        # Otherwise it's JSON — either a transient "loading" notice or an error.
        try:
            info = json.loads(payload.decode("utf-8"))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            raise AIVideoError(f"HF returned an unexpected non-video response for {model}") from exc
        if isinstance(info, dict) and info.get("error"):
            if info.get("estimated_time"):
                log.info("HF %s warming up; retrying in %ds", model, poll)
                time.sleep(poll)
                continue
            raise AIVideoError(f"HF error for {model}: {info.get('error')}")
        raise AIVideoError(f"HF unexpected response for {model}: {str(info)[:300]}")

    raise AIVideoError(f"HF generation timed out after {cfg.reel.ai_video.timeout_s}s")


def generate_ai_video(
    image_path: str | Path,
    scene_description: str,
    cfg: Config,
    output_path: str | Path,
    image_url: str | None = None,
) -> Path:
    """
    Generate an AI video.

    Raises AIVideoError on any provider failure.
    """

    if not cfg.reel.ai_video.enabled:
        raise AIVideoError("AI video is disabled")

    if cfg.reel.ai_video.mode == "off":
        raise AIVideoError("AI video mode is off")

    image = Path(image_path)
    output = Path(output_path)

    if not image.exists():
        raise AIVideoError(f"source image does not exist: {image}")

    provider = cfg.reel.ai_video.provider.lower()

    prompt = _pixverse_prompt(scene_description)

    log.info(
        "AI video: provider=%s image=%s",
        provider,
        image.name,
    )

    if provider == "pixverse":
        return _pixverse_generate(
            image,
            prompt,
            cfg,
            output,
            image_url=image_url,
        )

    if provider in {"huggingface", "hf"}:
        return _huggingface_generate(
            image,
            prompt,
            cfg,
            output,
        )

    raise AIVideoError(f"unsupported AI video provider: {provider}")
