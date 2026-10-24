"""Typeset infographic text onto a generated background.

Diffusion models (SD1.5 especially) cannot spell, so infographic profiles ask
the image model for a text-free background and draw the LLM-written headline
and takeaways here with Pillow. Every word on the slide is therefore crisp and
exactly what the LLM wrote.

Carousel layout (the format that earns saves for educational posts):
slide 1 = headline + "swipe" cue, slides 2..N = one takeaway each, with a
recap of every takeaway if there are more slides than takeaways. A single
photo gets the headline plus all takeaways as bullets.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache

from PIL import Image, ImageDraw, ImageFont

from .logging_utils import get_logger

log = get_logger("overlay")

# Bold sans fonts tried in order: Linux runners, macOS, Windows.
_FONT_CANDIDATES: tuple[str, ...] = (
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/segoeuib.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
)

_ACCENT = (94, 234, 212)  # teal, readable on the dark scrim
_TEXT = (255, 255, 255)
_MUTED = (200, 210, 220)


@dataclass
class SlideText:
    title: str
    body: list[str] = field(default_factory=list)
    kicker: str = ""  # small accent label above the title
    footer: str = ""  # small bottom-right label


def plan_slide(headline: str, points: list[str], index: int, total: int) -> SlideText:
    """Text for slide ``index`` of ``total`` (see module docstring)."""
    if total <= 1:
        return SlideText(title=headline, body=points, footer="Save for later")
    if index == 0:
        return SlideText(title=headline, footer="Swipe \u2192")
    footer = f"{index + 1}/{total}"
    # One takeaway per slide; the last slide recaps if points would be lost.
    leftover = index == total - 1 and len(points) > total - 1
    if index - 1 < len(points) and not leftover:
        return SlideText(title=points[index - 1], kicker=f"{index:02d}", footer=footer)
    return SlideText(title="Recap", body=points, kicker=headline, footer=footer)


@lru_cache(maxsize=16)
def _font(size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    override = os.environ.get("AUTOGRAM_FONT")
    for path in ((override,) if override else ()) + _FONT_CANDIDATES:
        if path and os.path.exists(path):
            return ImageFont.truetype(path, size)
    log.warning("no TrueType font found; using Pillow's default font")
    return ImageFont.load_default(size=size)


def _wrap(draw: ImageDraw.ImageDraw, text: str, font: object, max_w: int) -> list[str]:
    """Greedy word wrap by rendered pixel width."""
    lines: list[str] = []
    line = ""
    for word in text.split():
        trial = f"{line} {word}".strip()
        if draw.textlength(trial, font=font) <= max_w or not line:
            line = trial
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _scrim(img: Image.Image, top_frac: float) -> Image.Image:
    """Darken the top of the image with a vertical gradient for legibility."""
    w, h = img.size
    fade_h = int(h * top_frac)
    mask = Image.new("L", (1, h), 0)
    for y in range(h):
        if y < fade_h * 0.6:
            a = 200
        elif y < fade_h:
            a = int(200 * (1 - (y - fade_h * 0.6) / (fade_h * 0.4)))
        else:
            a = 0
        mask.putpixel((0, y), a)
    mask = mask.resize((w, h))
    black = Image.new("RGB", (w, h), (8, 10, 18))
    return Image.composite(black, img.convert("RGB"), mask)


def typeset(img: Image.Image, slide: SlideText) -> Image.Image:
    """Return a copy of ``img`` with ``slide`` drawn on a top scrim."""
    w, h = img.size
    margin = int(w * 0.08)
    max_w = w - 2 * margin
    draw_probe = ImageDraw.Draw(img)

    # Shrink the title until it fits in at most 4 lines.
    title_size = int(w * 0.085)
    while True:
        title_font = _font(title_size)
        title_lines = _wrap(draw_probe, slide.title, title_font, max_w)
        if len(title_lines) <= 4 or title_size <= int(w * 0.05):
            break
        title_size -= 4
    body_font = _font(int(w * 0.042))
    small_font = _font(int(w * 0.032))

    body_lines: list[str] = []
    for item in slide.body:
        wrapped = _wrap(draw_probe, item, body_font, max_w - int(w * 0.05))
        body_lines.extend([f"\u2022 {wrapped[0]}", *[f"   {x}" for x in wrapped[1:]]])

    title_lh = int(title_size * 1.15)
    body_lh = int(body_font.size * 1.4) if hasattr(body_font, "size") else 40
    block_h = len(title_lines) * title_lh + len(body_lines) * body_lh
    out = _scrim(img, top_frac=min(0.95, 0.25 + block_h / h + 0.1))
    draw = ImageDraw.Draw(out)

    y = int(h * 0.07)
    if slide.kicker:
        draw.text((margin, y), slide.kicker.upper(), font=small_font, fill=_ACCENT)
        y += int(w * 0.06)
    for line in title_lines:
        draw.text((margin, y), line, font=title_font, fill=_TEXT)
        y += title_lh
    if body_lines:
        y += int(w * 0.03)
        draw.line((margin, y, margin + int(w * 0.12), y), fill=_ACCENT, width=6)
        y += int(w * 0.04)
        for line in body_lines:
            draw.text((margin, y), line, font=body_font, fill=_MUTED)
            y += body_lh
    if slide.footer:
        fw = draw.textlength(slide.footer, font=small_font)
        draw.text(
            (w - margin - fw, h - int(h * 0.06)),
            slide.footer,
            font=small_font,
            fill=_TEXT,
            stroke_width=3,
            stroke_fill=(0, 0, 0),
        )
    return out
