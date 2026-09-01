"""Configuration and secrets.

Config (non-secret) is loaded from config/config.yaml and validated with
Pydantic.

Environment variables override YAML using:

    AUTOGRAM_<SECTION>__<KEY>=value

Examples:

    AUTOGRAM_IMAGE__STEPS=26
    AUTOGRAM_CONTENT__ACTIVE_PROFILE=romance
    AUTOGRAM_ROMANCE__THIRD_PERSON_PROBABILITY=0.45

Secrets are read only from the environment / .env.
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
# AUTOGRAM_-prefixed vars that are secrets, NOT config overrides — they must not
# be folded into the config dict by _apply_env_overrides (e.g. AUTOGRAM_ACCOUNTS
# is a JSON credentials blob, not the config.accounts list).
_ENV_OVERRIDE_EXCLUDE = {"AUTOGRAM_ACCOUNTS"}


# --------------------------------------------------------------------------- #
# Content profiles
# --------------------------------------------------------------------------- #


class ContentProfile(BaseModel):
    """Editorial/content definition for one active profile.

    All editorial content (theme, anchor, instructions, scene vocabulary) is
    supplied per profile in config/config.yaml. The defaults here are neutral,
    topic-agnostic scaffolding only — never bake a specific subject into code.
    """

    theme: str = ""

    system_prompt: str = (
        "You are a creative director generating one specific, photorealistic "
        "image scene. Prioritize clear faces, realistic anatomy, natural "
        "emotion, a clear physical action, and cinematic composition."
    )

    subject_instruction: str = (
        "Create one specific, visually concrete scene. "
        "The physical action must be clear from the image."
    )

    prompt_anchor: str = ""

    visual: dict[str, Any] = Field(default_factory=dict)


class ContentConfig(BaseModel):
    """Named editorial profiles."""

    active_profile: str = "romance"

    profiles: dict[str, ContentProfile] = Field(default_factory=dict)

    @property
    def active(self) -> ContentProfile:
        """Return the currently active profile."""
        profile = self.profiles.get(self.active_profile)

        if profile is None:
            if self.profiles:
                return next(iter(self.profiles.values()))

            return ContentProfile()

        return profile


# --------------------------------------------------------------------------- #
# Romance controls
# --------------------------------------------------------------------------- #


class RomanceConfig(BaseModel):
    """Structure + toggles for the proposal-scene brain.

    The descriptive text (ring style, third-person role/emotion, cinematic
    style) is content and lives in config/config.yaml's ``romance:`` block — the
    defaults here are intentionally empty so no specific subject is baked in.
    """

    enabled: bool = True

    proposal_directions: list[str] = Field(
        default_factory=lambda: [
            "boy_proposes_to_girl",
            "girl_proposes_to_boy",
        ]
    )

    third_person_probability: float = 0.45

    require_kneeling: bool = True
    require_flowers: bool = True
    require_ring: bool = True

    ring_style: str = ""

    third_person_role: str = ""

    third_person_emotion: str = ""

    cinematic_style: str = ""

    @field_validator("proposal_directions")
    @classmethod
    def _valid_proposal_directions(
        cls,
        values: list[str],
    ) -> list[str]:
        allowed = {
            "boy_proposes_to_girl",
            "girl_proposes_to_boy",
        }

        filtered = [value for value in values if value in allowed]

        if not filtered:
            return [
                "boy_proposes_to_girl",
                "girl_proposes_to_boy",
            ]

        return filtered

    @field_validator("third_person_probability")
    @classmethod
    def _valid_probability(
        cls,
        value: float,
    ) -> float:
        if value < 0.0 or value > 1.0:
            raise ValueError("romance.third_person_probability must be between 0 and 1")

        return value


# --------------------------------------------------------------------------- #
# Brief
# --------------------------------------------------------------------------- #


class BriefConfig(BaseModel):
    history_depth: int = 30
    dedupe_threshold: float = 85.0
    max_retries: int = 3

    axes: dict[str, list[str]] = Field(default_factory=dict)


# --------------------------------------------------------------------------- #
# LLM
# --------------------------------------------------------------------------- #


class LlmConfig(BaseModel):
    host_env: str = "OLLAMA_HOST"

    model: str = "qwen2.5:3b-instruct"

    hq_model: str = "qwen2.5:7b-instruct"

    ready_timeout_s: int = 120

    request_timeout_s: int = 180

    temperature: float = 0.8

    max_retries: int = 3


# --------------------------------------------------------------------------- #
# Image generation
# --------------------------------------------------------------------------- #


class ImageConfig(BaseModel):
    model: str = "Lykon/dreamshaper-8"

    hq_model: str = "black-forest-labs/FLUX.1-schnell"

    steps: int = 26

    guidance_scale: float = 6.5

    hq_steps: int = 4

    hq_guidance_scale: float = 0.0

    width: int = 512

    height: int = 512

    # Quality levers for the SD1.5 CPU path (ignored on the FLUX/GPU path):
    #   - DPM++ 2M Karras scheduler (sharper at the same step count; "" = default)
    #   - a fine-tuned VAE (crisper detail + color; "" disables)
    scheduler: str = "dpmpp_karras"
    vae: str = "stabilityai/sd-vae-ft-mse"
    # Optional hi-res fix: a second img2img pass at hires_scale that adds real
    # detail at ~2x the time. OFF by default so a multi-scene reel fits the
    # 60-min job budget; enable it and lower reel.num_scenes for max quality.
    hires_fix: bool = False
    hires_scale: float = 1.5
    hires_denoise: float = 0.4
    hires_steps: int = 16

    # Neutral, topic-agnostic scaffolding. The real, subject-specific templates
    # live per profile in config/config.yaml; keep placeholders in sync there.
    positive_template: str = (
        "{framing}, "
        "photograph of {characters}, "
        "{interaction}, "
        "{subject}, "
        "in {setting}, "
        "{lighting}, "
        "{mood}, "
        "{composition}, "
        "{color_palette}, "
        "{time_of_day}, "
        "{style_modifiers}, "
        "natural skin texture, "
        "realistic anatomy, "
        "highly detailed, "
        "sharp focus, "
        "professional photography, "
        "8k"
    )

    negative_template: str = (
        "illustration, painting, drawing, cartoon, anime, "
        "3d render, cgi, plastic skin, "
        "deformed, disfigured, mutated hands, extra fingers, "
        "extra limbs, bad anatomy, lowres, blurry, "
        "text, watermark, signature, jpeg artifacts, "
        "oversaturated, ugly, "
        "deformed face, distorted face, asymmetric face, "
        "extra faces, extra heads, fused faces, "
        "malformed face, blurry face, disfigured eyes, "
        "nudity, nsfw, revealing clothing, "
        "cleavage, lingerie, bikini, swimwear"
    )


# --------------------------------------------------------------------------- #
# Post-processing
# --------------------------------------------------------------------------- #


class PostprocConfig(BaseModel):
    aspect: str = "4:5"

    jpeg_quality: int = 92

    unsharp_radius: float = 1.2

    unsharp_percent: int = 80

    unsharp_threshold: int = 3

    max_bytes: int = 8 * 1024 * 1024

    @field_validator("aspect")
    @classmethod
    def _valid_aspect(
        cls,
        value: str,
    ) -> str:
        if value not in {
            "1:1",
            "4:5",
            "1.91:1",
        }:
            raise ValueError("aspect must be one of " "1:1, 4:5, 1.91:1")

        return value


# --------------------------------------------------------------------------- #
# Caption
# --------------------------------------------------------------------------- #


class CaptionConfig(BaseModel):
    tone: str = "warm, authentic, understated"

    emoji_budget: int = 2

    max_length: int = 2200

    hashtag_placement: str = "caption"

    @field_validator("hashtag_placement")
    @classmethod
    def _valid_placement(
        cls,
        value: str,
    ) -> str:
        if value not in {
            "caption",
            "comment",
        }:
            raise ValueError("hashtag_placement must be " "'caption' or 'comment'")

        return value


# --------------------------------------------------------------------------- #
# Hashtags
# --------------------------------------------------------------------------- #


class HashtagsConfig(BaseModel):
    min_count: int = 12

    max_count: int = 18

    tier_broad: float = 0.30

    tier_mid: float = 0.50

    tier_niche: float = 0.20

    brand_tags: list[str] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Quality gates
# --------------------------------------------------------------------------- #


class GatesConfig(BaseModel):
    nsfw: bool = True

    degenerate: bool = True

    profanity: bool = True

    degenerate_min_variance: float = 60.0

    degenerate_dark_mean: float = 12.0

    degenerate_bright_mean: float = 243.0


# --------------------------------------------------------------------------- #
# AI video
# --------------------------------------------------------------------------- #


class AiVideoConfig(BaseModel):
    enabled: bool = True

    mode: str = "auto"

    provider: str = "huggingface"

    ai_scene_indexes: list[int] = Field(default_factory=lambda: [0, 2])

    duration_s: int = 3

    timeout_s: int = 180

    poll_interval_s: int = 5

    fallback_to_ffmpeg: bool = True

    keep_intermediate: bool = False

    @field_validator("mode")
    @classmethod
    def _valid_mode(
        cls,
        value: str,
    ) -> str:
        if value not in {
            "auto",
            "off",
        }:
            raise ValueError("ai_video.mode must be 'auto' or 'off'")

        return value

    @field_validator("duration_s")
    @classmethod
    def _valid_duration(
        cls,
        value: int,
    ) -> int:
        if value < 1 or value > 10:
            raise ValueError("ai_video.duration_s must be between 1 and 10")

        return value

    @field_validator("timeout_s")
    @classmethod
    def _valid_timeout(
        cls,
        value: int,
    ) -> int:
        if value < 30:
            raise ValueError("ai_video.timeout_s must be >= 30")

        return value


# --------------------------------------------------------------------------- #
# Reel
# --------------------------------------------------------------------------- #


class ReelConfig(BaseModel):
    enabled: bool = False

    num_scenes: int = 4

    seconds_per_image: float = 3.2

    crossfade_s: float = 0.35

    fps: int = 30

    width: int = 1080

    height: int = 1920

    zoom: float = 1.12

    audio_dir: str = "assets/audio"

    ai_video: AiVideoConfig = Field(default_factory=AiVideoConfig)


# --------------------------------------------------------------------------- #
# State
# --------------------------------------------------------------------------- #


class CarouselConfig(BaseModel):
    """Multi-image (album) post controls."""

    enabled: bool = True
    # Instagram carousels allow 2-10 slides. Each slide is a distinct scene of
    # the same characters.
    num_slides: int = 4

    @field_validator("num_slides")
    @classmethod
    def _valid_slides(cls, value: int) -> int:
        if value < 2 or value > 10:
            raise ValueError("carousel.num_slides must be between 2 and 10")
        return value


class StateConfig(BaseModel):
    history_path: str = "state/history.json"

    session_path: str = "state/ig_session.json"

    out_dir: str = "out"


# --------------------------------------------------------------------------- #
# Main config
# --------------------------------------------------------------------------- #


class YoutubeConfig(BaseModel):
    """YouTube Shorts upload controls (used when POST_BACKEND=youtube)."""

    privacy_status: str = "private"
    category_id: str = "22"

    @field_validator("privacy_status")
    @classmethod
    def _valid_privacy(cls, value: str) -> str:
        if value not in {"private", "unlisted", "public"}:
            raise ValueError("youtube.privacy_status must be private, unlisted, or public")
        return value


class AccountConfig(BaseModel):
    """One linked social account driven from this repo.

    Non-secret only. Credentials are matched by ``id`` from the AUTOGRAM_ACCOUNTS
    JSON env secret (falling back to the flat IG_*/YOUTUBE_* env for a single
    implicit account). Different accounts can run different content profiles and
    content mixes, which is why one repo can now replace several.
    """

    id: str = "default"
    platform: str = "instagram"  # instagram | youtube
    backend: str = ""  # instagrapi | graph | youtube; "" -> derived from platform
    profile: str = ""  # content profile name; "" -> content.active_profile
    enabled: bool = True
    content_mix: dict[str, int] = Field(default_factory=dict)  # "" -> Config.content_mix
    audio_dir: str = ""  # override reel.audio_dir for this account

    def resolved_backend(self) -> str:
        if self.backend:
            return self.backend
        return "youtube" if self.platform == "youtube" else "instagrapi"


class Config(BaseModel):
    theme: str = ""

    seed_salt: str = "autogram-v1"

    # Linked accounts. Empty -> one implicit account from the flat env secrets
    # (back-compatible single-account behaviour).
    accounts: list[AccountConfig] = Field(default_factory=list)

    content: ContentConfig = Field(default_factory=ContentConfig)

    romance: RomanceConfig = Field(default_factory=RomanceConfig)

    brief: BriefConfig = Field(default_factory=BriefConfig)

    llm: LlmConfig = Field(default_factory=LlmConfig)

    image: ImageConfig = Field(default_factory=ImageConfig)

    postproc: PostprocConfig = Field(default_factory=PostprocConfig)

    caption: CaptionConfig = Field(default_factory=CaptionConfig)

    hashtags: HashtagsConfig = Field(default_factory=HashtagsConfig)

    gates: GatesConfig = Field(default_factory=GatesConfig)

    reel: ReelConfig = Field(default_factory=ReelConfig)

    carousel: CarouselConfig = Field(default_factory=CarouselConfig)

    # Weighted mix used to pick a content type per run when one isn't forced.
    # Weight 0 disables a type. Overridable per account.
    content_mix: dict[str, int] = Field(
        default_factory=lambda: {"photo": 1, "reel": 2, "carousel": 1}
    )

    state: StateConfig = Field(default_factory=StateConfig)

    youtube: YoutubeConfig = Field(default_factory=YoutubeConfig)

    @property
    def active_content(self) -> ContentProfile:
        """Active content profile, with its theme defaulted to the top-level theme.

        Lets a bare top-level ``theme:`` (or ``--description`` / ``AUTOGRAM_THEME``)
        drive a profile that does not set its own theme.
        """
        profile = self.content.active
        if not profile.theme:
            profile.theme = self.theme
        return profile


# --------------------------------------------------------------------------- #
# Secrets — environment only
# --------------------------------------------------------------------------- #


class Secrets(BaseSettings):
    """Credentials and environment-only settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        extra="ignore",
        case_sensitive=True,
    )

    POST_BACKEND: str = "instagrapi"

    # JSON array of per-account credentials, matched to config accounts by id:
    #   [{"id":"romance","ig_username":"..","ig_password":"..",...}, ...]
    # Lets multiple accounts (whose flat env-var names would otherwise collide)
    # live in one repo. Unset -> the flat IG_*/YOUTUBE_* vars below are used.
    AUTOGRAM_ACCOUNTS: str | None = None

    IG_USERNAME: str | None = None

    IG_PASSWORD: str | None = None

    IG_SESSION_B64: str | None = None

    IG_PROXY: str | None = None

    IG_ACCESS_TOKEN: str | None = None

    IG_USER_ID: str | None = None

    GITHUB_TOKEN: str | None = None

    GITHUB_REPOSITORY: str | None = None

    YOUTUBE_CLIENT_ID: str | None = None

    YOUTUBE_CLIENT_SECRET: str | None = None

    YOUTUBE_REFRESH_TOKEN: str | None = None

    OLLAMA_HOST: str = "http://127.0.0.1:11434"


# --------------------------------------------------------------------------- #
# Loading + environment overrides
# --------------------------------------------------------------------------- #


def _coerce(raw: str) -> Any:
    """Best-effort conversion of environment values."""

    low = raw.lower()

    if low in {
        "true",
        "false",
    }:
        return low == "true"

    try:
        if "." in raw:
            return float(raw)

        return int(raw)

    except ValueError:
        return raw


def _apply_env_overrides(
    data: dict[str, Any],
) -> dict[str, Any]:
    """Overlay AUTOGRAM_* variables onto YAML."""

    for env_key, env_value in os.environ.items():
        if not env_key.startswith(_ENV_PREFIX):
            continue
        if env_key in _ENV_OVERRIDE_EXCLUDE:
            continue

        path = env_key[len(_ENV_PREFIX) :].lower().split("__")

        cursor: dict[str, Any] = data

        for part in path[:-1]:
            next_value = cursor.get(part)

            if not isinstance(
                next_value,
                dict,
            ):
                next_value = {}
                cursor[part] = next_value

            cursor = next_value

        cursor[path[-1]] = _coerce(env_value)

    return data


def load_config(
    path: str | Path | None = None,
) -> Config:
    """Load YAML, apply environment overrides, validate."""

    cfg_path = Path(path) if path else DEFAULT_CONFIG_PATH

    data: dict[str, Any] = {}

    if cfg_path.exists():
        loaded = yaml.safe_load(cfg_path.read_text(encoding="utf-8"))

        if loaded:
            data = loaded

    data = _apply_env_overrides(data)

    return Config.model_validate(data)


def load_secrets() -> Secrets:
    """Load environment/.env secrets."""
    return Secrets()
