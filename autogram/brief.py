"""Creative-brief variation: theme -> a fresh, non-repeating brief (LLM).

Variety is guaranteed three ways:
  1. A seeded RNG (run date + config salt) pre-selects axis hints (camera
     angle, season, focal length, subject scale) injected into the prompt.
  2. The prompt includes the last N briefs and demands explicit divergence.
  3. Near-duplicate subjects (rapidfuzz token_set_ratio > threshold) are
     rejected and retried, up to max_retries.
  4. Character descriptors and location data loaded from characters.json
     ensure consistent couple portrayal and never-repeated scenic locations.
"""

from __future__ import annotations

import hashlib
import json
import random
import re
from pathlib import Path
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


def load_characters_data(path: str = "config/characters.json") -> dict[str, Any]:
    """Load character descriptors and location data from JSON."""
    try:
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (FileNotFoundError, json.JSONDecodeError) as exc:
        log.warning("characters.json not found or invalid: %s, using defaults", exc)
        return {"characters": {}, "locations": {}}


def flatten_locations(locations_dict: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """Flatten nested location categories into a single list."""
    all_locations = []
    for category, scenarios in locations_dict.items():
        if isinstance(scenarios, list):
            all_locations.extend(scenarios)
    return all_locations


def select_unique_location(
    rng: random.Random, 
    all_locations: list[dict[str, str]], 
    history_locations: list[str]
) -> dict[str, str] | None:
    """Select a location not previously used. Return None if all exhausted."""
    available = [
        loc for loc in all_locations 
        if loc.get("name", "") not in history_locations
    ]
    if not available:
        log.warning("all locations exhausted; cycling through all locations")
        available = all_locations
    return rng.choice(available) if available else None


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
    characters_data: dict[str, Any],
    selected_location: dict[str, str] | None,
) -> list[dict[str, str]]:
    schema = (
        '{"subject": "string", "setting": "string", "lighting": "string", '
        '"mood": "string", "composition": "string", "color_palette": "string", '
        '"time_of_day": "string", "style_modifiers": ["string", ...]}'
    )
    system = (
        "You are an art director generating a single creative brief for one "
        "photographic image of a romantic South Asian couple. Respond ONLY with a JSON object matching this schema "
        f"exactly: {schema}. No prose, no code fences."
    )
    
    # Build character descriptor section
    char_section = ""
    if characters_data.get("characters"):
        female = characters_data["characters"].get("female", {})
        male = characters_data["characters"].get("male", {})
        char_section = (
            f"\nCOUPLE DESCRIPTORS:\n"
            f"Female: {female.get('identity', '')}. "
            f"Features: {female.get('facial_features', '')}. "
            f"Hair: {female.get('hair', '')}. "
            f"Accessories: {female.get('accessories', '')}.\n"
            f"Male: {male.get('identity', '')}. "
            f"Features: {male.get('facial_features', '')}. "
            f"Hair: {male.get('hair', '')}. "
            f"Beard: {male.get('facial_hair', '')}.\n"
        )
    
    # Build location section
    location_section = ""
    if selected_location:
        location_section = (
            f"\nLOCATION/SETTING:\n"
            f"Name: {selected_location.get('name', '')}\n"
            f"Description: {selected_location.get('description', '')}\n"
            f"Lighting: {selected_location.get('lighting', '')}\n"
            f"Mood: {selected_location.get('mood', '')}\n"
        )
    
    hints = "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in axis_hints.items())
    prev_lines = (
        "\n".join(f"- {b.get('subject', '?')} / {b.get('mood', '?')}" for b in recent_briefs)
        or "(none yet)"
    )
    user = (
        f"Standing theme (stay on-brand): {cfg.theme}\n"
        f"{char_section}"
        f"{location_section}"
        f"\nIncorporate these pre-selected creative constraints:\n{hints}\n\n"
        f"These are the most recent briefs already used — your brief MUST be "
        f"clearly different in subject and composition from ALL of them:\n{prev_lines}\n\n"
        f"Produce one fresh, specific, visually concrete brief featuring the couple in the described location. "
        f"The 'subject' must be a distinct scene, not a rephrasing of a previous one."
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


def extract_location_from_history(history_briefs: list[dict[str, Any]]) -> list[str]:
    """Extract location names from recent briefs if available."""
    locations = []
    for brief in history_briefs:
        # Check if location metadata exists in the brief
        if "location_name" in brief:
            locations.append(brief["location_name"])
    return locations


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
    
    # Load character and location data
    characters_data = load_characters_data()
    all_locations = flatten_locations(characters_data.get("locations", {}))
    history_locations = extract_location_from_history(recent_briefs)
    selected_location = select_unique_location(rng, all_locations, history_locations)
    
    if selected_location:
        log.info("selected location: %s", selected_location.get("name", "unknown"))
    else:
        log.warning("no locations available or all exhausted")

    error_feedback: str | None = None
    for attempt in range(1, cfg.brief.max_retries + 1):
        try:
            raw = client.chat_json(
                model=model,
                messages=_build_messages(
                    cfg, axis_hints, recent_briefs, error_feedback, 
                    characters_data, selected_location
                ),
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
