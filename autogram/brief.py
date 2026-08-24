"""Creative-brief variation: theme -> a fresh, non-repeating brief (LLM).

Variety is guaranteed three ways:
  1. A seeded RNG (run date + config salt) pre-selects axis hints (camera
     angle, season, focal length, subject scale) injected into the prompt.
  2. The prompt includes the last N briefs and demands explicit divergence.
  3. Near-duplicate subjects (rapidfuzz token_set_ratio > threshold) are
     rejected and retried, up to max_retries.
"""

from __future__ import annotations

import hashlib
import random
import re
from typing import Any

from pydantic import BaseModel, Field, ValidationError
from rapidfuzz import fuzz

from .caption import OllamaClient, OllamaError
from .config import Config
from .logging_utils import get_logger

log = get_logger("brief")


class Brief(BaseModel):
    subject: str
    setting: str
    lighting: str
    mood: str
    composition: str
    color_palette: str
    time_of_day: str
    style_modifiers: list[str] = Field(default_factory=list)


def compute_seed(run_date: str, salt: str) -> int:
    """Deterministic 31-bit seed from the run date (YYYY-MM-DD) and salt."""
    digest = hashlib.sha256(f"{run_date}|{salt}".encode()).hexdigest()
    return int(digest[:8], 16)


def select_axis_hints(rng: random.Random, axes: dict[str, list[str]]) -> dict[str, str]:
    """Pre-select one value per configured axis using the seeded RNG."""
    return {axis: rng.choice(values) for axis, values in axes.items() if values}


def _normalize_subject(subject: str) -> str:
    return re.sub(r"\s+", " ", subject.lower().strip())


def is_near_duplicate(subject: str, history_subjects: list[str], threshold: float) -> bool:
    """True if subject is a near-duplicate of any historical subject."""
    norm = _normalize_subject(subject)
    for prev in history_subjects:
        if fuzz.token_set_ratio(norm, _normalize_subject(prev)) > threshold:
            return True
    return False


def render_prompts(brief: Brief, cfg: Config) -> tuple[str, str]:
    """Render (positive, negative) Stable Diffusion prompts from the brief."""
    fields: dict[str, Any] = brief.model_dump()
    fields["style_modifiers"] = ", ".join(brief.style_modifiers)
    positive = cfg.image.positive_template.format(**fields)
    negative = cfg.image.negative_template
    # Collapse any accidental double commas/space from empty fields.
    positive = re.sub(r"(,\s*){2,}", ", ", positive).strip(" ,")
    return positive, negative


def _build_messages(
    cfg: Config,
    axis_hints: dict[str, str],
    recent_briefs: list[dict[str, Any]],
    error_feedback: str | None,
) -> list[dict[str, str]]:
    schema = (
        '{"subject": "string", "setting": "string", "lighting": "string", '
        '"mood": "string", "composition": "string", "color_palette": "string", '
        '"time_of_day": "string", "style_modifiers": ["string", ...]}'
    )
    system = (
        "You are an art director generating a single creative brief for one "
        "photographic image. Respond ONLY with a JSON object matching this schema "
        f"exactly: {schema}. No prose, no code fences."
    )
    hints = "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in axis_hints.items())
    prev_lines = (
        "\n".join(f"- {b.get('subject', '?')} / {b.get('mood', '?')}" for b in recent_briefs)
        or "(none yet)"
    )
    user = (
        f"Standing theme (stay on-brand): {cfg.theme}\n\n"
        f"Incorporate these pre-selected creative constraints:\n{hints}\n\n"
        f"These are the most recent briefs already used — your brief MUST be "
        f"clearly different in subject and composition from ALL of them:\n{prev_lines}\n\n"
        f"Produce one fresh, specific, visually concrete brief. The 'subject' must "
        f"be a distinct scene, not a rephrasing of a previous one."
    )
    if error_feedback:
        user += (
            f"\n\nYour previous reply was invalid: {error_feedback}\nReply with valid JSON only."
        )
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _fallback_brief(cfg: Config, axis_hints: dict[str, str], seed: int) -> Brief:
    """Deterministic brief if the LLM never returns valid JSON."""
    log.warning("using deterministic fallback brief")
    return Brief(
        subject=f"{cfg.theme} (variation {seed % 1000})",
        setting=cfg.theme,
        lighting=axis_hints.get("season", "soft") + " light",
        mood="serene",
        composition=axis_hints.get("camera_angle", "eye-level")
        + ", "
        + axis_hints.get("subject_scale", "medium shot"),
        color_palette="muted neutral tones",
        time_of_day=axis_hints.get("time_of_day", "morning"),
        style_modifiers=[axis_hints.get("focal_length", "35mm"), "photographic"],
    )


def generate_brief(
    client: OllamaClient,
    cfg: Config,
    seed: int,
    run_date: str,
    history_subjects: list[str],
    recent_briefs: list[dict[str, Any]],
    model: str,
) -> Brief:
    """Generate a fresh, non-duplicate brief varied from the standing theme."""
    rng = random.Random(compute_seed(run_date, cfg.seed_salt) ^ seed)
    axis_hints = select_axis_hints(rng, cfg.brief.axes)
    log.info("axis hints: %s", axis_hints)

    error_feedback: str | None = None
    for attempt in range(1, cfg.brief.max_retries + 1):
        try:
            raw = client.chat_json(
                model=model,
                messages=_build_messages(cfg, axis_hints, recent_briefs, error_feedback),
                seed=seed + attempt,  # perturb so a retry actually diverges
                temperature=cfg.llm.temperature,
            )
            brief = Brief.model_validate(raw)
        except (OllamaError, ValidationError) as exc:
            error_feedback = str(exc)[:300]
            log.warning(
                "brief attempt %d/%d invalid: %s", attempt, cfg.brief.max_retries, error_feedback
            )
            continue

        if is_near_duplicate(brief.subject, history_subjects, cfg.brief.dedupe_threshold):
            error_feedback = (
                f"subject '{brief.subject}' is too similar to a recent post; "
                f"choose a substantially different subject"
            )
            log.warning("brief attempt %d rejected as near-duplicate", attempt)
            continue

        log.info("brief accepted: %s", brief.subject)
        return brief

    return _fallback_brief(cfg, axis_hints, seed)
