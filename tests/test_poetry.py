from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image

from autogram.config import Config, load_config
from autogram.poetry import (
    Poem,
    _load_library,
    apply_to_image,
    pick_poem,
    poetry_active,
    render_layer,
)
from autogram.scene import Brief


def _cfg(profile: str = "travel") -> Config:
    cfg = load_config()
    cfg.content.active_profile = profile
    return cfg


def test_library_loads_with_poets():
    poems, keywords = _load_library("config/poetry.md")
    poets = {p.poet for p in poems}
    assert {"Rumi", "Faiz", "Ghalib", "Tagore", "Kahlil Gibran"} <= poets
    assert len(poems) >= 9_000
    assert "love" in keywords
    assert all(0 <= p.likeability <= 100 for p in poems)


def test_shayari_library_is_default():
    cfg = _cfg()
    assert cfg.poetry.library_path == "config/shayari.md"
    poems, keywords = _load_library(cfg.poetry.library_path)
    poets = {p.poet for p in poems}
    assert {"Kabir", "Rahim", "Ghalib", "Original"} <= poets
    assert len(poems) >= 200
    assert {"love", "journey", "chai", "ghar", "dosti"} <= set(keywords)


def test_original_shayari_uses_configured_credit():
    cfg = _cfg()
    brief = Brief(subject="a couple proposing with a ring")
    for credit in ("", "@myhandle"):
        cfg.poetry.original_credit = credit
        picks = [pick_poem(cfg, brief, seed=s) for s in range(30)]
        assert all(p is not None and p.poet.lower() != "original" for p in picks)
        assert any(p.poet == credit for p in picks if p)


def test_layer_without_credit_renders():
    layer = render_layer(Poem(lines=("Chai, dost,", "aur baatein"), poet=""), (1080, 1350))
    assert layer.getpixel((540, 40))[3] > 0


def test_poetry_skips_infographic_profile():
    assert poetry_active(_cfg("travel"))
    assert not poetry_active(_cfg("ai_tools"))


def test_pick_matches_mood():
    brief = Brief(subject="a fishing boat on the sea at sunset", setting="quiet harbour shore")
    poem = pick_poem(_cfg(), brief, seed=1)
    assert poem is not None
    assert {"sea", "sky", "journey", "longing", "time", "nature"} & set(poem.tags)


def test_pick_avoids_recent():
    brief = Brief(subject="a couple holding hands, love")
    first = pick_poem(_cfg(), brief, seed=3)
    assert first is not None
    again = pick_poem(_cfg(), brief, seed=3, recent_texts=[first.text])
    assert again is not None and again.text != first.text


def test_apply_to_image_keeps_size(tmp_path):
    p = tmp_path / "x.jpg"
    Image.new("RGB", (1080, 1350), (120, 140, 160)).save(p)
    apply_to_image(
        p, Poem(lines=("Wherever you stand,", "be the soul of that place."), poet="Rumi")
    )
    out = Image.open(p)
    assert out.size == (1080, 1350)
    # Top (poem) changed, bottom untouched.
    assert out.getpixel((540, 120)) != (120, 140, 160)
    bottom = out.getpixel((540, 1300))
    assert all(abs(a - b) < 6 for a, b in zip(bottom, (120, 140, 160), strict=True))


def test_reel_layer_poem_at_top_bottom_clear():
    layer = render_layer(Poem(lines=("a", "b"), poet="Faiz"), (1080, 1920), vertical=True)
    assert layer.mode == "RGBA"
    assert layer.getpixel((10, 1910))[3] == 0  # lower frame stays clear
    assert layer.getpixel((10, 300))[3] > 0  # shaded band behind the verse at the top


def test_pick_favours_likeable_poems():
    brief = Brief(subject="a couple in love under the stars")
    picks = [pick_poem(_cfg(), brief, seed=s) for s in range(40)]
    assert sum(p.likeability for p in picks if p) / len(picks) >= 75


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not installed")
def test_build_reel_with_overlay(tmp_path):
    from autogram.render.reel import build_reel

    cfg = _cfg()
    cfg.reel.audio_dir = str(tmp_path / "none")
    imgs = []
    for i, c in enumerate([(200, 80, 80), (80, 200, 80)]):
        p = tmp_path / f"s{i}.jpg"
        Image.new("RGB", (1080, 1350), c).save(p)
        imgs.append(p)
    ov = tmp_path / "poem.png"
    render_layer(Poem(lines=("line one", "line two"), poet="Rumi"), (1080, 1920), True).save(ov)
    out = build_reel(imgs, cfg, tmp_path / "r.mp4", seed=5, overlay=ov)
    assert out.exists()
    res = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(out),
        ],
        capture_output=True,
        text=True,
    )
    assert "video" in res.stdout and "audio" in res.stdout


def test_caption_prompt_carries_the_shayari():
    from autogram.caption import _build_messages

    verse = "Train ki seeti, station ki chai / Safar ki yaadein kabhi na jaayein bhai"
    user = _build_messages(Brief(subject="chai at a station"), _cfg(), None, verse)[1]["content"]
    assert verse in user and "mood" in user
    plain = _build_messages(Brief(subject="chai at a station"), _cfg(), None)[1]["content"]
    assert "shayari" not in plain


def test_verse_block_opens_caption_with_credit():
    from autogram.content.base import verse_block

    block = verse_block(Poem(lines=("Rahiman dhaaga prem ka,", "mat todo chatkaay"), poet="Rahim"))
    assert block.startswith("“Rahiman") and block.endswith("— Rahim")
    assert "—" not in verse_block(Poem(lines=("a", "b"), poet=""))
