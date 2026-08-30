from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from autogram.brief import Brief
from autogram.config import (
    CaptionConfig,
    Config,
    ContentConfig,
    ContentProfileConfig,
    GatesConfig,
    HashtagsConfig,
    PostprocConfig,
)


@pytest.fixture
def cfg() -> Config:
    return Config(
        content=ContentConfig(active_profile="test", profiles={"test": ContentProfileConfig(theme="minimalist Scandinavian interiors with warm morning light")}),
        hashtags=HashtagsConfig(min_count=3, max_count=6, brand_tags=["autogram", "slowdesign"]),
        caption=CaptionConfig(emoji_budget=2, max_length=2200, hashtag_placement="caption"),
        postproc=PostprocConfig(aspect="1:1", max_bytes=8 * 1024 * 1024),
        gates=GatesConfig(nsfw=False, degenerate=True, profanity=True),
    )


@pytest.fixture
def brief() -> Brief:
    return Brief(
        subject="a cozy reading nook by a bright window",
        setting="a Scandinavian living room",
        lighting="soft warm morning light",
        mood="serene",
        composition="eye-level, medium shot",
        color_palette="muted neutral tones",
        time_of_day="early morning",
        style_modifiers=["35mm", "photographic"],
    )


@pytest.fixture
def gradient_image() -> Image.Image:
    """A high-variance horizontal gradient (passes the degenerate gate)."""
    arr = np.tile(np.arange(0, 256, dtype="uint8"), (256, 1))
    return Image.fromarray(arr).convert("RGB")
