"""Relatable poetry overlay: a short verse + poet credit on every post.

The library (``config/poetry.md``, ~10,000 entries built by
``scripts/build_poetry_library.py``) holds verses by Rumi, Tagore, Gibran,
Khayyam, Hafiz, Kabir, Faiz, Ghalib, Dickinson ... each with mood tags and a
♥ likeability score. A poem is matched to the post's mood (keywords from the
brief vs. its tags), favouring high-♥ verses and avoiding recently used ones.

The verse sits at the TOP of the frame, in the same fixed spot on every photo
and carousel slide. For Reels it is a separate transparent PNG that FFmpeg
composites AFTER the camera motion, so it stays perfectly still while the
scene pans and zooms underneath it.
"""

from __future__ import annotations

import os
import random
import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PIL import Image, ImageDraw, ImageFilter, ImageFont

from .logging_utils import get_logger

if TYPE_CHECKING:
    from .config import Config
    from .scene import Brief

log = get_logger("poetry")

# Elegant italic serif first, then plain serif, then sans (Linux, macOS, Windows).
_ITALIC_FONTS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Italic.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Italic.ttf",
    "C:/Windows/Fonts/georgiai.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
    "C:/Windows/Fonts/georgia.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
    "C:/Windows/Fonts/segoeui.ttf",
)
_CREDIT_FONTS: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
    "/usr/share/fonts/truetype/liberation2/LiberationSerif-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Georgia Bold.ttf",
    "C:/Windows/Fonts/georgiab.ttf",
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
)

_TEXT = (255, 255, 255, 255)
_CREDIT = (255, 214, 153, 255)  # warm gold, reads well over any photo
_SHADOW = (0, 0, 0)


@dataclass(frozen=True)
class Poem:
    lines: tuple[str, ...]
    poet: str
    tags: tuple[str, ...] = ()
    likeability: float = 50.0  # 0-100, from the library's ♥ score

    @property
    def text(self) -> str:
        return " / ".join(self.lines)

    def as_record(self) -> dict[str, str]:
        return {"text": self.text, "poet": self.poet}


# --------------------------------------------------------------------------- #
# Library + selection
# --------------------------------------------------------------------------- #


_REPO_ROOT = Path(__file__).resolve().parent.parent


def _resolve(path: str) -> Path:
    p = Path(path)
    if p.is_absolute() or p.exists():
        return p.resolve()
    return (_REPO_ROOT / p).resolve()


def _load_library(path: str) -> tuple[tuple[Poem, ...], dict[str, tuple[str, ...]]]:
    p = _resolve(path)
    if not p.exists():
        log.warning("poetry library %s not found; no poem will be added", path)
        return (), {}
    return _parse_library(str(p), p.stat().st_mtime)


_HEADING = re.compile(r"^###\s+\S+\s+·\s+(?P<poet>.+?)(?:\s+·\s+♥\s*(?P<score>[\d.]+))?\s*$")
_KEYWORD_LINE = re.compile(r"^-\s*(?P<tag>[\w-]+)\s*:\s*(?P<words>.+)$")


@lru_cache(maxsize=4)
def _parse_library(path: str, _mtime: float) -> tuple[tuple[Poem, ...], dict[str, tuple[str, ...]]]:
    """Parse config/poetry.md (see scripts/build_poetry_library.py).

    ``## Tag keywords`` holds ``- tag: word, word`` lines; each poem is a
    ``### <id> · <poet> · ♥ <score>`` heading, a ``tags:`` line and ``>`` lines.
    """
    poems: list[Poem] = []
    keywords: dict[str, tuple[str, ...]] = {}
    section = ""
    cur: dict[str, Any] | None = None

    def flush() -> None:
        if cur and cur["lines"]:
            poems.append(
                Poem(
                    lines=tuple(cur["lines"]),
                    poet=cur["poet"],
                    tags=tuple(cur["tags"]),
                    likeability=cur["score"],
                )
            )

    for raw in Path(path).read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if line.startswith("## "):
            flush()
            cur = None
            section = line[3:].strip().lower()
            continue
        if section.startswith("tag keywords"):
            m = _KEYWORD_LINE.match(line)
            if m:
                keywords[m["tag"].lower()] = tuple(
                    w.strip().lower() for w in m["words"].split(",") if w.strip()
                )
            continue
        m = _HEADING.match(line)
        if m:
            flush()
            score = float(m["score"]) if m["score"] else 50.0
            cur = {"poet": m["poet"].strip(), "score": score, "tags": [], "lines": []}
        elif cur is not None and line.lower().startswith("tags:"):
            cur["tags"] = [t.strip().lower() for t in line[5:].split(",") if t.strip()]
        elif cur is not None and line.startswith(">"):
            text = line[1:].strip()
            if text:
                cur["lines"].append(text)
    flush()
    return tuple(poems), keywords


def poetry_active(cfg: Config) -> bool:
    pc = cfg.poetry
    if not pc.enabled:
        return False
    profiles = pc.applies_to_profiles
    return not profiles or cfg.content.active_profile in profiles


def _brief_words(brief: Brief, theme: str) -> set[str]:
    text = " ".join(
        str(x)
        for x in (
            brief.subject,
            brief.setting,
            brief.lighting,
            brief.mood,
            brief.time_of_day,
            brief.color_palette,
            brief.location_name,
            brief.interaction,
            brief.romantic_details,
            brief.proposal_action,
            theme,
        )
        if x
    ).lower()
    return set(re.findall(r"[a-z]+", text))


def _score(poem: Poem, words: set[str], keywords: dict[str, tuple[str, ...]]) -> int:
    score = 0
    for tag in poem.tags:
        triggers = {tag, *keywords.get(tag, ())}
        score += sum(1 for t in triggers if t in words)
    return score


def pick_poem(
    cfg: Config,
    brief: Brief,
    seed: int,
    recent_texts: list[str] | None = None,
) -> Poem | None:
    """Pick a likeable poem whose tags match the brief, skipping recent ones.

    Candidates are the poems within one point of the best mood match; among
    them the pick is weighted heavily toward a high ♥ likeability score, so
    the library's best verses appear most often while the rest still rotate.
    """
    poems, keywords = _load_library(cfg.poetry.library_path)
    if not poems:
        return None
    recent = set(recent_texts or [])
    pool = [p for p in poems if p.text not in recent] or list(poems)

    words = _brief_words(brief, cfg.active_content.theme)
    scored = [(_score(p, words, keywords), p) for p in pool]
    best = max(s for s, _ in scored)
    candidates = [p for s, p in scored if best > 0 and s >= max(1, best - 1)] or pool
    weights = [(max(p.likeability, 1.0) / 100.0) ** 6 for p in candidates]
    poem = random.Random(seed).choices(candidates, weights=weights, k=1)[0]
    log.info(
        "poem (match %d/%d, ♥ %g, %d candidates): %s — %s",
        _score(poem, words, keywords),
        best,
        poem.likeability,
        len(candidates),
        poem.text,
        poem.poet,
    )
    return poem


# --------------------------------------------------------------------------- #
# Rendering
# --------------------------------------------------------------------------- #


@lru_cache(maxsize=32)
def _font(size: int, credit: bool) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    override = os.environ.get("AUTOGRAM_POETRY_FONT")
    candidates = _CREDIT_FONTS if credit else _ITALIC_FONTS
    for path in ((override,) if override and not credit else ()) + candidates:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: object, max_w: int) -> list[str]:
    out: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            out.append(line)
            line = word
    if line:
        out.append(line)
    return out


def _wrap_balanced(draw: ImageDraw.ImageDraw, text: str, font: object, max_w: int) -> list[str]:
    """Wrap into as few lines as fit, but split them evenly (no orphan word)."""
    lines = _wrap(draw, text, font, max_w)
    if len(lines) <= 1:
        return lines
    target = int(draw.textlength(text, font=font) / len(lines))
    while target < max_w:
        trial = _wrap(draw, text, font, target)
        if len(trial) == len(lines):
            return trial
        target += 8
    return lines


def render_layer(
    poem: Poem, size: tuple[int, int], vertical: bool = False, position: str = "top"
) -> Image.Image:
    """Transparent RGBA layer with the poem centred at the top (or bottom).

    ``vertical`` (Reels, 9:16) keeps the block clear of Instagram's overlays:
    below the "Reels" header at the top, above the caption/buttons at the bottom.
    """
    w, h = size
    layer = Image.new("RGBA", size, (0, 0, 0, 0))
    probe = ImageDraw.Draw(layer)
    max_w = int(w * 0.84)

    # Shrink until every verse line fits on one line (a couplet reads best
    # unbroken); below the minimum size, wrap instead.
    size_px = int(w * (0.050 if vertical else 0.046))
    min_px = int(w * 0.036)
    while True:
        font = _font(size_px, credit=False)
        wrapped = [ln for raw in poem.lines for ln in _wrap_balanced(probe, raw, font, max_w)]
        if len(wrapped) <= len(poem.lines) or size_px <= min_px:
            break
        size_px -= 2
    credit_font = _font(int(size_px * 0.78), credit=True)
    credit = f"\u2014 {poem.poet}"

    line_h = int(size_px * 1.38)
    gap = int(size_px * 0.55)
    credit_h = int(size_px * 0.78 * 1.3)
    block_h = len(wrapped) * line_h + gap + credit_h

    if position == "bottom":
        bottom = int(h * (0.76 if vertical else 0.93))
        top = bottom - block_h
    else:
        top = int(h * (0.10 if vertical else 0.06))
        bottom = top + block_h

    # Soft dark band behind the text so it reads over bright skies or snow.
    pad = int(size_px * 1.4)
    band = Image.new("L", size, 0)
    band_top = -pad if position != "bottom" else top - pad  # top: fade from the edge
    ImageDraw.Draw(band).rectangle((0, band_top, w, bottom + pad), fill=120)
    band = band.filter(ImageFilter.GaussianBlur(pad * 0.8))
    shade = Image.new("RGBA", size, (5, 6, 12, 255))
    shade.putalpha(band)
    layer = Image.alpha_composite(layer, shade)

    draw = ImageDraw.Draw(layer)
    stroke = max(1, size_px // 18)
    y = top
    for ln in wrapped:
        lw = draw.textlength(ln, font=font)
        draw.text(
            ((w - lw) / 2, y),
            ln,
            font=font,
            fill=_TEXT,
            stroke_width=stroke,
            stroke_fill=_SHADOW,
        )
        y += line_h
    y += gap
    cw = draw.textlength(credit, font=credit_font)
    draw.text(
        ((w - cw) / 2, y),
        credit,
        font=credit_font,
        fill=_CREDIT,
        stroke_width=stroke,
        stroke_fill=_SHADOW,
    )
    return layer


def apply_to_image(path: Path, poem: Poem, jpeg_quality: int = 92, position: str = "top") -> Path:
    """Draw ``poem`` onto the JPEG at ``path`` in place (same spot on every slide)."""
    with Image.open(path) as src:
        base = src.convert("RGBA")
    layer = render_layer(poem, base.size, position=position)
    out = Image.alpha_composite(base, layer).convert("RGB")
    out.save(path, format="JPEG", quality=jpeg_quality, optimize=True)
    return path


def write_reel_overlay(
    poem: Poem, width: int, height: int, out_path: Path, position: str = "top"
) -> Path:
    """Write a full-frame transparent PNG for FFmpeg to overlay on the Reel."""
    out_path.parent.mkdir(parents=True, exist_ok=True)
    layer = render_layer(poem, (width, height), vertical=True, position=position)
    layer.save(out_path, format="PNG")
    return out_path
