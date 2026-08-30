"""Creative-brief variation: theme -> a fresh, non-repeating brief (LLM).

Variety is guaranteed several ways:
  1. A seeded RNG (per-run stamp + config salt) pre-selects axis hints (camera
     angle, season, focal length, subject scale) plus a photographic style
     (interaction, mood, composition, lighting, color grading) injected into
     both the LLM prompt and, deterministically, the image prompt.
  2. The prompt includes the last N briefs and demands explicit divergence.
  3. Near-duplicate subjects (rapidfuzz token_set_ratio > threshold) are
     rejected and retried, up to max_retries.
  4. A profile-specific prompt anchor is injected directly into the Stable-Diffusion prompt.
  5. Locations are rotated using recorded history so a place is not reused
     until the pool is exhausted.
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
    # Structured scene metadata (set in code, not by the LLM) so location
    # rotation is recorded to history and the couple's interaction varies.
    location_name: str = ""
    interaction: str = ""
    # Deterministic per-scene framing (shot distance / angle / alignment /
    # candid cue) injected at the FRONT of the image prompt so distance and
    # composition actually vary instead of every image being the same portrait.
    framing: str = ""


def compute_seed(run_date: str, salt: str) -> int:
    """Deterministic 31-bit seed from an input string (date or stamp) and salt."""
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


def flatten_locations(locations_dict: dict[str, list[dict[str, str]]]) -> list[dict[str, str]]:
    """Flatten nested location categories into a single list."""
    all_locations: list[dict[str, str]] = []
    for scenarios in locations_dict.values():
        if isinstance(scenarios, list):
            all_locations.extend(scenarios)
    return all_locations


def select_unique_location(
    rng: random.Random,
    all_locations: list[dict[str, str]],
    history_locations: list[str],
) -> dict[str, str] | None:
    """Select a location not previously used. Cycle when the pool is exhausted."""
    available = [loc for loc in all_locations if loc.get("name", "") not in history_locations]
    if not available:
        log.warning("all locations used within history window; cycling through all locations")
        available = all_locations
    return rng.choice(available) if available else None


def _pick(rng: random.Random, data: dict[str, Any], key: str) -> str:
    """Pick one value from the active content profile, or ''."""
    values = data.get(key)
    if isinstance(values, list) and values:
        return str(rng.choice(values))
    return ""


def _pick_trend(rng: random.Random, trends: dict[str, Any], key: str) -> str:
    values = trends.get(key)
    if isinstance(values, list) and values:
        return str(rng.choice(values))
    return ""


# Framing variation — curated, compact, SD-friendly. Placed FIRST in the image
# prompt so shot distance/angle/alignment actually change per image instead of
# every frame being the same centered two-person portrait.
# Shot distances are face-SAFE: front-facing shots stay close enough that faces
# get enough pixels for SD to render them cleanly, and the far/wide shots are
# framed from behind or facing the view so no front faces exist to be mangled.
# (SD1.5 deforms faces that occupy only a small part of a 512px frame.)
_SHOT_DISTANCES = [
    "extreme close-up of their faces, sharp facial detail",
    "close-up portrait of both faces",
    "medium shot from the waist up, faces clearly visible",
    "three-quarter shot from head to knees, faces clearly visible",
    "over-the-shoulder shot focusing on one clear face",
    "wide shot seen from behind, the couple facing away toward the view",
    "environmental wide shot from behind, couple silhouetted against the scenery",
    "full-body shot from behind as they walk into the landscape",
]
_CAMERA_ANGLES = [
    "eye-level angle",
    "low angle looking up",
    "high angle looking down",
    "slight dutch tilt",
    "overhead top-down view",
    "shot from behind the couple",
    "side profile view",
    "three-quarter back view",
]
_ALIGNMENTS = [
    "rule-of-thirds composition, couple off to one side",
    "couple on the left third",
    "couple on the right third",
    "couple low in the lower third with negative space above",
    "framed by natural foreground elements",
    "off-center with strong leading lines",
    "asymmetric composition with depth layers",
]
_CANDID_CUES = [
    "candid unposed moment, not looking at the camera",
    "caught mid-laugh, natural genuine expression",
    "walking together with natural motion",
    "spontaneous documentary-style street photograph",
    "natural candid gesture, gazing at each other",
    "quiet candid instant looking into the distance",
    "in-between moment, relaxed and unaware of the camera",
]


def select_framing(rng: random.Random) -> str:
    """Pick a compact shot/framing string (distance, angle, alignment, candid)."""
    return (
        f"{rng.choice(_SHOT_DISTANCES)}, "
        f"{rng.choice(_CAMERA_ANGLES)}, "
        f"{rng.choice(_ALIGNMENTS)}, "
        f"{rng.choice(_CANDID_CUES)}"
    )


def select_style(rng: random.Random, characters_data: dict[str, Any]) -> dict[str, str]:
    """Select a photographic style + interaction combination for this run.

    Combined with location rotation, framing variation, and a unique per-run
    seed this yields an effectively non-repeating combinatorial space
    (locations x interactions x framing x moods x compositions x lighting x
    grading), so the platform can produce large volumes of varied content.
    """
    trends = characters_data.get("photography_trends", {})
    if not isinstance(trends, dict):
        trends = {}
    return {
        "framing": select_framing(rng),
        "interaction": _pick(rng, characters_data, "interaction_styles"),
        "emotion": _pick(rng, characters_data, "moods_and_emotions"),
        "composition": _pick_trend(rng, trends, "compositions"),
        "lighting_style": _pick_trend(rng, trends, "lighting_styles"),
        "color_grading": _pick_trend(rng, trends, "color_grading"),
        "depth_of_field": _pick_trend(rng, trends, "depth_of_field"),
    }


def build_character_block(cfg: Config) -> str:
    """Return the selected profile's deterministic image prompt anchor.

    Despite its historical name, an anchor may describe recurring people, a
    product, an illustration style, or be empty for topic-led content.
    """
    return cfg.active_content.prompt_anchor.strip()

def render_prompts(brief: Brief, cfg: Config, characters_block: str = "") -> tuple[str, str]:
    """Render (positive, negative) Stable Diffusion prompts from the brief.

    ``characters_block`` is injected first so the couple's identity dominates
    the prompt (kept consistent across runs); the brief supplies the varying
    scene, and the config template appends photoreal quality cues.
    """
    fields: dict[str, Any] = brief.model_dump()
    fields["style_modifiers"] = ", ".join(brief.style_modifiers)
    fields["characters"] = characters_block
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
    style: dict[str, str],
) -> list[dict[str, str]]:
    schema = (
        '{"subject": "string", "setting": "string", "lighting": "string", '
        '"mood": "string", "composition": "string", "color_palette": "string", '
        '"time_of_day": "string", "style_modifiers": ["string", ...]}'
    )
    system = (
        f"{cfg.active_content.system_prompt.strip()} Respond ONLY with a "
        f"JSON object matching this schema exactly: {schema}. No prose, no code fences."
    )

    # Build character descriptor section.
    char_section = ""
    if characters_data.get("characters"):
        female = characters_data["characters"].get("female", {})
        male = characters_data["characters"].get("male", {})
        char_section = (
            "\nCOUPLE DESCRIPTORS (keep these two people identical every time):\n"
            f"Female: {female.get('identity', '')}. "
            f"Features: {female.get('facial_features', '')}. "
            f"Hair: {female.get('hair', '')}. "
            f"Accessories: {female.get('accessories', '')}.\n"
            f"Male: {male.get('identity', '')}. "
            f"Features: {male.get('facial_features', '')}. "
            f"Hair: {male.get('hair', '')}. "
            f"Beard: {male.get('facial_hair', '')}.\n"
        )

    # Build location section.
    location_section = ""
    if selected_location:
        location_section = (
            "\nLOCATION/SETTING (place the couple here):\n"
            f"Name: {selected_location.get('name', '')}\n"
            f"Description: {selected_location.get('description', '')}\n"
            f"Lighting: {selected_location.get('lighting', '')}\n"
            f"Mood: {selected_location.get('mood', '')}\n"
        )

    style_section = ""
    if any(style.values()):
        style_section = (
            "\nPHOTOGRAPHIC DIRECTION (weave these in):\n"
            f"Framing/shot: {style.get('framing', '')}\n"
            f"Interaction: {style.get('interaction', '')}\n"
            f"Emotion: {style.get('emotion', '')}\n"
            f"Composition: {style.get('composition', '')}\n"
            f"Lighting style: {style.get('lighting_style', '')}\n"
            f"Color grading: {style.get('color_grading', '')}\n"
            f"Depth of field: {style.get('depth_of_field', '')}\n"
            "Make the shot distance and framing match the Framing/shot above; "
            "do NOT default to a centered two-person portrait every time.\n"
        )

    hints = "\n".join(f"- {k.replace('_', ' ')}: {v}" for k, v in axis_hints.items())
    prev_lines = (
        "\n".join(f"- {b.get('subject', '?')} / {b.get('mood', '?')}" for b in recent_briefs)
        or "(none yet)"
    )
    user = (
        f"Active content profile: {cfg.content.active_profile}\n"
        f"Standing theme (stay on-brand): {cfg.active_content.theme}\n"
        f"{char_section}"
        f"{location_section}"
        f"{style_section}"
        f"\nIncorporate these pre-selected creative constraints:\n{hints}\n\n"
        f"These are the most recent briefs already used ? your brief MUST be "
        f"clearly different in subject and composition from ALL of them:\n{prev_lines}\n\n"
        f"{cfg.active_content.subject_instruction}\n"
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


def _apply_scene(
    brief: Brief,
    selected_location: dict[str, str] | None,
    style: dict[str, str],
) -> Brief:
    """Stamp guaranteed scene variety onto a brief (place + interaction).

    Done in code (not left to the LLM) so location rotation is recorded and the
    couple's pose/interaction genuinely changes every run regardless of what the
    model returned.
    """
    if selected_location:
        brief.location_name = selected_location.get("name", "")
        # A concise place cue keeps the SD prompt within the CLIP token budget.
        if brief.location_name:
            brief.setting = brief.location_name
        loc_lighting = selected_location.get("lighting", "")
        if loc_lighting:
            brief.lighting = loc_lighting
    interaction = style.get("interaction", "")
    if interaction:
        brief.interaction = interaction
    brief.framing = style.get("framing", "")
    return brief


def _fallback_brief(
    cfg: Config,
    axis_hints: dict[str, str],
    seed: int,
    selected_location: dict[str, str] | None,
    style: dict[str, str],
) -> Brief:
    """Deterministic brief if the LLM never returns valid JSON."""
    log.warning("using deterministic fallback brief")
    brief = Brief(
        subject=f"{cfg.active_content.theme} (variation {seed % 1000})",
        setting=cfg.active_content.theme,
        lighting=axis_hints.get("season", "soft") + " light",
        mood=style.get("emotion") or "serene",
        composition=style.get("composition")
        or (
            axis_hints.get("camera_angle", "eye-level")
            + ", "
            + axis_hints.get("subject_scale", "medium shot")
        ),
        color_palette=style.get("color_grading") or "muted neutral tones",
        time_of_day=axis_hints.get("time_of_day", "morning"),
        style_modifiers=[axis_hints.get("focal_length", "35mm"), "photographic"],
    )
    return _apply_scene(brief, selected_location, style)


def extract_location_from_history(history_briefs: list[dict[str, Any]]) -> list[str]:
    """Extract location names from recent briefs so they can be rotated out."""
    locations: list[str] = []
    for brief in history_briefs:
        name = brief.get("location_name")
        if name:
            locations.append(str(name))
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

    # Load character/location/style data and rotate a fresh location + style.
    characters_data = cfg.active_content.visual
    all_locations = flatten_locations(characters_data.get("locations", {}))
    history_locations = extract_location_from_history(recent_briefs)
    selected_location = select_unique_location(rng, all_locations, history_locations)
    style = select_style(rng, characters_data)

    if selected_location:
        log.info("selected location: %s", selected_location.get("name", "unknown"))
    else:
        log.warning("no locations available or all exhausted")
    log.info("style: %s", {k: v for k, v in style.items() if v})

    error_feedback: str | None = None
    for attempt in range(1, cfg.brief.max_retries + 1):
        try:
            raw = client.chat_json(
                model=model,
                messages=_build_messages(
                    cfg,
                    axis_hints,
                    recent_briefs,
                    error_feedback,
                    characters_data,
                    selected_location,
                    style,
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

        brief = _apply_scene(brief, selected_location, style)
        log.info("brief accepted: %s @ %s", brief.subject, brief.location_name or "(no location)")
        return brief

    return _fallback_brief(cfg, axis_hints, seed, selected_location, style)
