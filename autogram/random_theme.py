"""Random, non-repetitive prompts for ``random_theme`` profiles.

Each image draws one value from every pool with an OS-entropy seed, so two runs
do not share a prompt (the run date is deliberately not used). The assembled
prompt is held to ``max_prompt_words``: low-priority parts are dropped first and
the subject is never dropped. CLIP only reads 77 tokens, so the word budget
keeps the whole prompt inside that window.

Stdlib only, so it can be unit-tested without torch or pydantic installed.
"""

from __future__ import annotations

import random
import re
from collections.abc import Mapping, Sequence

# Highest priority first. Parts are dropped from the END when over budget.
PART_ORDER: tuple[str, ...] = (
    "subject",
    "setting",
    "lighting",
    "lens",
    "mood",
    "composition",
    "palette",
)
REQUIRED_PARTS: frozenset[str] = frozenset({"subject"})


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _word_count(text: str) -> int:
    return len(text.split())


def new_rng() -> random.Random:
    """A Random seeded from OS entropy: different on every call."""
    return random.Random(random.SystemRandom().getrandbits(64))


def pick_parts(pools: Mapping[str, Sequence[str]], rng: random.Random) -> dict[str, str]:
    """Choose one value from each non-empty pool."""
    parts: dict[str, str] = {}
    for key in PART_ORDER:
        values = [v.strip() for v in pools.get(key, ()) if v and v.strip()]
        if values:
            parts[key] = rng.choice(values)
    return parts


def assemble_prompt(parts: Mapping[str, str], quality_suffix: str, max_words: int) -> str:
    """Join parts + quality suffix within ``max_words``.

    Drops the lowest-priority parts until the prompt fits. The subject is kept.
    As a last resort the text is trimmed to ``max_words`` words.
    """
    kept = dict(parts)

    def render() -> str:
        seq = [kept[k] for k in PART_ORDER if k in kept]
        if quality_suffix.strip():
            seq.append(quality_suffix.strip())
        return ", ".join(seq)

    prompt = render()
    for key in reversed(PART_ORDER):
        if _word_count(prompt) <= max_words:
            break
        if key in REQUIRED_PARTS:
            continue
        kept.pop(key, None)
        prompt = render()

    if _word_count(prompt) > max_words:
        prompt = " ".join(prompt.split()[:max_words]).rstrip(" ,")
    return prompt


def build_random_prompt(
    pools: Mapping[str, Sequence[str]],
    rng: random.Random,
    *,
    quality_suffix: str,
    max_words: int,
    recent_subjects: Sequence[str] = (),
    tries: int = 8,
) -> tuple[str, dict[str, str]]:
    """Return ``(prompt, parts)``, re-rolling a few times to avoid recent subjects."""
    recent = {_norm(s) for s in recent_subjects if s}
    parts = pick_parts(pools, rng)
    for _ in range(max(0, tries)):
        if _norm(parts.get("subject", "")) not in recent:
            break
        parts = pick_parts(pools, rng)
    prompt = assemble_prompt(parts, quality_suffix, max_words)
    return prompt, parts


def brief_fields(parts: Mapping[str, str], prompt: str) -> dict[str, object]:
    """Map random parts onto the Brief fields that captions and history read."""
    lens = parts.get("lens", "")
    setting = parts.get("setting", "")
    return {
        "subject": parts.get("subject", ""),
        "setting": setting,
        "lighting": parts.get("lighting", ""),
        "mood": parts.get("mood", ""),
        "composition": parts.get("composition", ""),
        "color_palette": parts.get("palette", ""),
        "time_of_day": "",
        "style_modifiers": [lens] if lens else [],
        "location_name": setting,
        "framing": lens,
        "interaction": "",
        "image_prompt": prompt,
    }
