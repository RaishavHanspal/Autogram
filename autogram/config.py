"""Configuration and secrets.

Config (non-secret) is loaded from config/config.yaml and validated with
pydantic. Environment variables override YAML using the scheme:

    AUTOGRAM_<SECTION>__<KEY>=value      e.g. AUTOGRAM_IMAGE__STEPS=4
    AUTOGRAM_<TOPLEVEL>=value            e.g. AUTOGRAM_THEME="cats in space"

Secrets are read ONLY from the environment (never YAML) via pydantic-settings.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

DEFAULT_CONFIG_PATH = Path("config/config.yaml")
_ENV_PREFIX = "AUTOGRAM_"


# --------------------------------------------------------------------------- #
# Non-secret config sections
# --------------------------------------------------------------------------- #
class BriefConfig(BaseModel):
    history_depth: int = 30
    dedupe_threshold: float = 85.0
    max_retries: int = 3
    axes: dict[str, list[str]] = Field(default_factory=dict)


class LlmConfig(BaseModel):
    host_env: str = "OLLAMA_HOST"
    model: str = "qwen2.5:3b-instruct"
    hq_model: str = "qwen2.5:7b-instruct"
    ready_timeout_s: int = 120
    request_timeout_s: int = 180
    temperature: float = 0.8
    max_retries: int = 3


class ImageConfig(BaseModel):
    # CPU default: a photoreal SD1.5 checkpoint (diffusers format). Much more
    # realistic than sd-turbo at the cost of more sampling steps (minutes on a
    # free CPU runner, still well within the 60-min job budget).
    model: str = "Lykon/dreamshaper-8"
    hq_model: str = "black-forest-labs/FLUX.1-schnell"
    steps: int = 26  # CPU photoreal model wants ~20-30 steps
    guidance_scale: float = 6.5  # and real CFG (turbo/schnell want 0.0)
    # Sampling used only on the GPU/FLUX path (schnell is distilled: 4 steps, CFG 0).
    hq_steps: int = 4
    hq_guidance_scale: float = 0.0
    # Native 4:5 (Instagram portrait) so no pixels are cropped away and faces
    # get more verticals. 512x640 is a safe CPU size; 640x800 is sharper but slower.
    width: int = 512
    height: int = 640
    # Quality levers for the CPU SD1.5 path (ignored on the FLUX/GPU path):
    #   - DPM++ 2M Karras scheduler (sharper at the same step count)
    #   - a fine-tuned VAE (crisper detail, better color; "" disables)
    scheduler: str = "dpmpp_karras"
    vae: str = "stabilityai/sd-vae-ft-mse"
    # Optional hi-res fix: a second img2img pass at hires_scale that adds real
    # detail (the biggest SD1.5 quality lever) at ~2x the time. Default OFF so a
    # 4-scene reel never blows the 60-min job budget unattended — enable it and
    # lower reel.num_scenes if you want maximum quality.
    hires_fix: bool = False
    hires_scale: float = 1.5
    hires_denoise: float = 0.4
    hires_steps: int = 16
    positive_template: str = (
        "{framing}, candid photograph of {characters}, {interaction}, {subject}, "
        "in {setting}, {lighting}, {mood}, {color_palette}, {time_of_day}, "
        "{style_modifiers}, shot on DSLR, natural skin texture, realistic, "
        "highly detailed, sharp focus, professional photography, 8k"
    )
    negative_template: str = (
        "illustration, painting, drawing, cartoon, anime, 3d render, cgi, "
        "plastic skin, deformed, disfigured, mutated hands, extra fingers, "
        "extra limbs, bad anatomy, lowres, blurry, text, watermark, signature, "
        "jpeg artifacts, oversaturated, ugly, "
        "deformed face, distorted face, asymmetric face, extra faces, extra heads, "
        "fused faces, malformed face, blurry face, disfigured eyes, "
        "nudity, nsfw, revealing clothing, cleavage, lingerie, bikini, swimwear"
    )


class PostprocConfig(BaseModel):
    aspect: str = "4:5"
    jpeg_quality: int = 92
    unsharp_radius: float = 1.2
    unsharp_percent: int = 80
    unsharp_threshold: int = 3
    max_bytes: int = 8 * 1024 * 1024

    @field_validator("aspect")
    @classmethod
    def _valid_aspect(cls, v: str) -> str:
        if v not in {"1:1", "4:5", "1.91:1"}:
            raise ValueError(f"aspect must be one of 1:1, 4:5, 1.91:1 (got {v})")
        return v


class CaptionConfig(BaseModel):
    tone: str = "calm, warm, understated"
    emoji_budget: int = 2
    max_length: int = 2200
    hashtag_placement: str = "caption"

    @field_validator("hashtag_placement")
    @classmethod
    def _valid_placement(cls, v: str) -> str:
        if v not in {"caption", "comment"}:
            raise ValueError("hashtag_placement must be 'caption' or 'comment'")
        return v


class HashtagsConfig(BaseModel):
    min_count: int = 12
    max_count: int = 18
    tier_broad: float = 0.30
    tier_mid: float = 0.50
    tier_niche: float = 0.20
    brand_tags: list[str] = Field(default_factory=list)


class GatesConfig(BaseModel):
    nsfw: bool = True
    degenerate: bool = True
    profanity: bool = True
    degenerate_min_variance: float = 60.0
    degenerate_dark_mean: float = 12.0
    degenerate_bright_mean: float = 243.0


class AiVideoConfig(BaseModel):
    enabled: bool = True
    # auto = attempt AI video and fall back to FFmpeg
    # off = never attempt AI video
    mode: str = "auto"
    # Currently supported provider.
    provider: str = "pixverse"
    # Scene indexes that should use AI video.
    ai_scene_indexes: list[int] = Field(default_factory=lambda: [0, 2])

    # Requested AI video duration.
    duration_s: int = 3
    # Maximum time to wait for a provider.
    timeout_s: int = 180
    # Poll interval.
    poll_interval_s: int = 5
    # Never make AI video failure fatal.
    fallback_to_ffmpeg: bool = True
    # Whether intermediate AI MP4s should remain in out/.
    keep_intermediate: bool = False

    @field_validator("mode")
    @classmethod
    def _valid_mode(cls, v: str) -> str:
        if v not in {"auto", "off"}:
            raise ValueError("ai_video.mode must be 'auto' or 'off'")
        return v

    @field_validator("duration_s")
    @classmethod
    def _valid_duration(cls, v: int) -> int:
        if v < 1 or v > 10:
            raise ValueError("ai_video.duration_s must be between 1 and 10")
        return v

    @field_validator("timeout_s")
    @classmethod
    def _valid_timeout(cls, v: int) -> int:
        if v < 30:
            raise ValueError("ai_video.timeout_s must be >= 30")
        return v


class ReelConfig(BaseModel):
    # When enabled, several scenes are assembled into a vertical Reel.
    enabled: bool = False
    # Number of generated scenes.
    num_scenes: int = 4
    # Average scene duration before transitions.
    seconds_per_image: float = 3.2
    # Transition duration.
    crossfade_s: float = 0.35
    fps: int = 30
    width: int = 1080
    height: int = 1920
    # FFmpeg fallback zoom.
    zoom: float = 1.12
    # Royalty-free audio directory.
    audio_dir: str = "assets/audio"
    # Optional external AI image-to-video.
    ai_video: AiVideoConfig = Field(default_factory=AiVideoConfig)


class StateConfig(BaseModel):
    history_path: str = "state/history.json"
    session_path: str = "state/ig_session.json"
    out_dir: str = "out"


class Config(BaseModel):
    theme: str = "minimalist Scandinavian interiors with warm morning light"
    seed_salt: str = "autogram-v1"
    brief: BriefConfig = Field(default_factory=BriefConfig)
    llm: LlmConfig = Field(default_factory=LlmConfig)
    image: ImageConfig = Field(default_factory=ImageConfig)
    postproc: PostprocConfig = Field(default_factory=PostprocConfig)
    caption: CaptionConfig = Field(default_factory=CaptionConfig)
    hashtags: HashtagsConfig = Field(default_factory=HashtagsConfig)
    gates: GatesConfig = Field(default_factory=GatesConfig)
    reel: ReelConfig = Field(default_factory=ReelConfig)
    state: StateConfig = Field(default_factory=StateConfig)


# --------------------------------------------------------------------------- #
# Secrets — env only
# --------------------------------------------------------------------------- #
class Secrets(BaseSettings):
    """Credentials and env-only settings. Never sourced from YAML."""

    model_config = SettingsConfigDict(env_file=".env", extra="ignore", case_sensitive=True)

    POST_BACKEND: str = "instagrapi"

    IG_USERNAME: str | None = None
    IG_PASSWORD: str | None = None
    IG_SESSION_B64: str | None = None
    IG_PROXY: str | None = None

    IG_ACCESS_TOKEN: str | None = None
    IG_USER_ID: str | None = None

    GITHUB_TOKEN: str | None = None
    GITHUB_REPOSITORY: str | None = None

    OLLAMA_HOST: str = "http://127.0.0.1:11434"


# --------------------------------------------------------------------------- #
# Loading + env overrides
# --------------------------------------------------------------------------- #
def _coerce(raw: str) -> Any:
    """Best-effort coercion of an env-string override to a scalar."""
    low = raw.lower()
    if low in {"true", "false"}:
        return low == "true"
    try:
        if "." in raw:
            return float(raw)
        return int(raw)
    except ValueError:
        return raw


def _apply_env_overrides(data: dict[str, Any]) -> dict[str, Any]:
    """Overlay AUTOGRAM_* env vars onto the parsed YAML dict."""
    for env_key, env_val in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        path = env_key[len(_ENV_PREFIX) :].lower().split("__")
        cursor: dict[str, Any] = data
        for part in path[:-1]:
            nxt = cursor.get(part)
            if not isinstance(nxt, dict):
                nxt = {}
                cursor[part] = nxt
            cursor = nxt
        cursor[path[-1]] = _coerce(env_val)
    return data


def load_config(path: str | Path | None = None) -> Config:
    """Load and validate config from YAML, then apply env overrides."""
    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH
    data: dict[str, Any] = {}
    if cfg_path.exists():
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))
        if loaded:
            data = loaded
    data = _apply_env_overrides(data)
    return Config.model_validate(data)


def load_secrets() -> Secrets:
    return Secrets()