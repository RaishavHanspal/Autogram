"""Creative brief generation for the romantic-couple profile.

The scene is deliberately controlled in Python rather than relying entirely
on the LLM. Each run deterministically selects:

    * boy proposes to girl OR girl proposes to boy
    * optional third woman in a love triangle
    * proposal action
    * ring / flowers
    * emotional reactions
    * cinematic framing
    * location
    * photographic style

The selected proposal metadata is stamped onto Brief and injected directly
into the final Stable Diffusion prompt so the image generator receives the
same scene direction even when the LLM varies its JSON response.
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

log = get_logger("scene")


class Brief(BaseModel):
    subject: str
    setting: str
    lighting: str
    mood: str
    composition: str
    color_palette: str
    time_of_day: str
    style_modifiers: list[str] = Field(default_factory=list)

    # Existing history/scene metadata.
    location_name: str = ""
    interaction: str = ""
    framing: str = ""

    # Romance-specific metadata.
    proposal_direction: str = ""
    proposal_action: str = ""
    third_person_present: bool = False
    third_person_role: str = ""
    romantic_details: str = ""


def compute_seed(run_date: str, salt: str) -> int:
    """Return a deterministic 31-bit seed."""
    digest = hashlib.sha256(f"{run_date}|{salt}".encode()).hexdigest()

    return int(digest[:8], 16)


def select_axis_hints(
    rng: random.Random,
    axes: dict[str, list[str]],
) -> dict[str, str]:
    """Select one value from every configured creative axis."""
    return {axis: rng.choice(values) for axis, values in axes.items() if values}


def _normalize_subject(subject: str) -> str:
    return re.sub(
        r"\s+",
        " ",
        subject.lower().strip(),
    )


def is_near_duplicate(
    subject: str,
    history_subjects: list[str],
    threshold: float,
) -> bool:
    """Reject subjects that are too similar to recent subjects."""
    norm = _normalize_subject(subject)

    for previous in history_subjects:
        if (
            fuzz.token_set_ratio(
                norm,
                _normalize_subject(previous),
            )
            > threshold
        ):
            return True

    return False


def flatten_locations(
    locations_dict: dict[str, list[dict[str, str]]],
) -> list[dict[str, str]]:
    """Flatten location categories into one list."""
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
    """Select a location not recently used."""
    available = [
        location for location in all_locations if location.get("name", "") not in history_locations
    ]

    if not available:
        log.warning("all locations used within history window; cycling through pool")
        available = all_locations

    return rng.choice(available) if available else None


def _pick(
    rng: random.Random,
    data: dict[str, Any],
    key: str,
) -> str:
    """Pick a string from a configured list."""
    values = data.get(key)

    if isinstance(values, list) and values:
        return str(rng.choice(values))

    return ""


def _pick_trend(
    rng: random.Random,
    trends: dict[str, Any],
    key: str,
) -> str:
    """Pick a photographic trend."""
    values = trends.get(key)

    if isinstance(values, list) and values:
        return str(rng.choice(values))

    return ""


# ---------------------------------------------------------------------------
# Framing
# ---------------------------------------------------------------------------

_SHOT_DISTANCES = [
    "medium shot from the waist up with both faces clearly visible",
    "three-quarter shot from head to knees with the proposal action visible",
    "full-body cinematic shot showing the kneeling proposal clearly",
    "medium-wide cinematic shot with the couple dominant in the frame",
    "three-quarter view emphasizing the kneeling proposer and recipient",
    "over-the-shoulder view from behind the recipient toward the proposer",
    "side-profile cinematic view showing both emotional reactions",
    "wide cinematic romantic scene with the proposal couple prominent",
]


_CAMERA_ANGLES = [
    "eye-level cinematic angle",
    "slightly low romantic hero angle",
    "gentle three-quarter angle",
    "slightly elevated cinematic angle",
    "side profile view",
    "over-the-shoulder perspective",
    "low cinematic angle emphasizing the proposal",
]


_ALIGNMENTS = [
    "rule-of-thirds composition",
    "proposer on one third and recipient on the opposite third",
    "couple centered with strong cinematic depth",
    "proposal action placed in the lower third",
    "asymmetric composition with depth layers",
    "foreground flowers framing the couple",
    "strong leading lines toward the kneeling proposer",
]


_CANDID_CUES = [
    "genuine emotional expressions",
    "natural romantic body language",
    "authentic surprise and heartfelt reaction",
    "caught in an intimate emotional moment",
    "expressive eyes and realistic emotion",
    "cinematic candid emotional reaction",
]


def select_framing(rng: random.Random) -> str:
    """Select a proposal-friendly composition."""
    return (
        f"{rng.choice(_SHOT_DISTANCES)}, "
        f"{rng.choice(_CAMERA_ANGLES)}, "
        f"{rng.choice(_ALIGNMENTS)}, "
        f"{rng.choice(_CANDID_CUES)}"
    )


# ---------------------------------------------------------------------------
# Romance scene selection
# ---------------------------------------------------------------------------

_DEFAULT_PROPOSAL_DIRECTIONS = [
    "boy_proposes_to_girl",
    "girl_proposes_to_boy",
]


_BOY_PROPOSALS = [
    (
        "boy kneeling on one knee before the girl, "
        "opening a ring box and presenting her with a clearly visible "
        "marquise-cut engagement ring while holding a romantic bouquet"
    ),
    (
        "boy down on one knee, extending a marquise-cut engagement ring "
        "toward the girl while holding fresh flowers in his other hand"
    ),
    (
        "boy kneeling romantically before the girl, offering a delicate "
        "marquise-cut engagement ring and flowers with a deeply emotional "
        "expression"
    ),
    (
        "grand marriage proposal with the boy kneeling before the girl, "
        "presenting a sparkling marquise-cut ring and a beautiful bouquet"
    ),
]


_GIRL_PROPOSALS = [
    (
        "girl kneeling on one knee before the boy and presenting him with "
        "an elegant engagement ring while looking deeply emotional"
    ),
    (
        "girl down on one knee, offering the boy an engagement ring and "
        "flowers while he reacts with genuine surprise and emotion"
    ),
    (
        "girl making a heartfelt marriage proposal to the boy, kneeling "
        "romantically and presenting an engagement ring"
    ),
    (
        "girl kneeling during a grand romantic proposal, holding out an "
        "engagement ring toward the boy as he realizes what is happening"
    ),
]


_FLOWERS = [
    "fresh red roses",
    "a romantic bouquet of red and white roses",
    "a lush bouquet of roses and delicate flowers",
    "a large elegant bouquet of fresh flowers",
    "soft pastel flowers mixed with romantic roses",
]


_THIRD_GIRL_ROLES = [
    (
        "third woman who is secretly in love with the boy, "
        "watching the proposal from a respectful distance"
    ),
    (
        "heartbroken woman experiencing unrequited love for the boy, "
        "standing apart from the couple"
    ),
    ("devastated third woman who loves the boy but realizes he has " "chosen the other girl"),
    (
        "third woman emotionally attached to the boy, watching the "
        "proposal alone from the background"
    ),
]


_THIRD_GIRL_EMOTIONS = [
    "crying with visible tears on her cheeks",
    "quietly sobbing with tears streaming down her face",
    "heartbroken and visibly crying",
    "tearful eyes and trembling emotional expression",
    "deep sadness with restrained sobbing",
]


_ROMANTIC_STYLES = [
    (
        "grand cinematic Indian romantic-film atmosphere, "
        "emotional storytelling, expressive eyes, dramatic romantic lighting"
    ),
    (
        "sweeping cinematic Indian love-story atmosphere, "
        "heartfelt emotion, elegant romantic composition"
    ),
    ("iconic Indian romantic-film energy, " "grand emotional storytelling and expressive faces"),
    (
        "lush cinematic romance, emotional performances, "
        "dreamlike Indian romantic-film atmosphere"
    ),
]


def _configured_proposal_directions(cfg: Config) -> list[str]:
    """Return configured proposal directions with safe defaults."""
    directions = cfg.romance.proposal_directions

    valid = [
        direction
        for direction in directions
        if direction
        in {
            "boy_proposes_to_girl",
            "girl_proposes_to_boy",
        }
    ]

    return valid or _DEFAULT_PROPOSAL_DIRECTIONS


def select_proposal_scene(
    rng: random.Random,
    cfg: Config,
) -> dict[str, Any]:
    """Select a complete deterministic romantic proposal scene."""

    directions = _configured_proposal_directions(cfg)

    direction = rng.choice(directions)

    if direction == "boy_proposes_to_girl":
        proposal_action = f"{rng.choice(_BOY_PROPOSALS)}; " f"{rng.choice(_FLOWERS)}"
    else:
        proposal_action = f"{rng.choice(_GIRL_PROPOSALS)}; " f"{rng.choice(_FLOWERS)}"

    third_probability = max(
        0.0,
        min(
            1.0,
            cfg.romance.third_person_probability,
        ),
    )

    third_person_present = rng.random() < third_probability

    third_role = ""
    third_emotion = ""

    if third_person_present:
        third_role = rng.choice(_THIRD_GIRL_ROLES)
        third_emotion = rng.choice(_THIRD_GIRL_EMOTIONS)

    return {
        "proposal_direction": direction,
        "proposal_action": proposal_action,
        "third_person_present": third_person_present,
        "third_person_role": third_role,
        "third_person_emotion": third_emotion,
        "romantic_details": (cfg.romance.cinematic_style or rng.choice(_ROMANTIC_STYLES)),
    }


def select_style(
    rng: random.Random,
    cfg: Config,
    characters_data: dict[str, Any],
) -> dict[str, str]:
    """Select photographic and romance direction."""

    trends = characters_data.get(
        "photography_trends",
        {},
    )

    if not isinstance(trends, dict):
        trends = {}

    proposal = select_proposal_scene(
        rng,
        cfg,
    )

    return {
        "framing": select_framing(rng),
        "interaction": _pick(
            rng,
            characters_data,
            "interaction_styles",
        ),
        "emotion": _pick(
            rng,
            characters_data,
            "moods_and_emotions",
        ),
        "composition": _pick_trend(
            rng,
            trends,
            "compositions",
        ),
        "lighting_style": _pick_trend(
            rng,
            trends,
            "lighting_styles",
        ),
        "color_grading": _pick_trend(
            rng,
            trends,
            "color_grading",
        ),
        "depth_of_field": _pick_trend(
            rng,
            trends,
            "depth_of_field",
        ),
        **{key: str(value) for key, value in proposal.items()},
    }


def build_character_block(cfg: Config) -> str:
    """Return the configured recurring-character prompt anchor."""
    return cfg.active_content.prompt_anchor.strip()


def _render_romantic_prompt(
    brief: Brief,
    cfg: Config,
) -> str:
    """Create deterministic high-priority romance instructions."""

    parts = [
        "photorealistic cinematic Indian romance",
        "realistic human anatomy",
        "natural realistic skin",
        "expressive realistic faces",
        "strong emotional storytelling",
    ]

    if brief.proposal_direction == "boy_proposes_to_girl":
        parts.extend(
            [
                "BOY PROPOSES TO GIRL",
                "the male character is the proposer",
                "the boy is clearly kneeling on one knee",
                "the boy is facing the girl",
                "the boy presents the girl with a marquise-cut engagement ring",
                "the marquise-cut ring is clearly visible",
                "the boy gives the girl a romantic bouquet of flowers",
                "the girl is receiving the proposal",
                "the girl has a loving emotional reaction",
                "grand romantic Indian-film hero energy",
            ]
        )

    elif brief.proposal_direction == "girl_proposes_to_boy":
        parts.extend(
            [
                "GIRL PROPOSES TO BOY",
                "the female character is the proposer",
                "the girl is clearly kneeling on one knee",
                "the girl is facing the boy",
                "the girl presents the boy with an engagement ring",
                "the engagement ring is clearly visible",
                "the girl gives the boy romantic flowers",
                "the boy is receiving the proposal",
                "the boy has a surprised emotional reaction",
                "grand cinematic Indian romantic-film energy",
            ]
        )

    if cfg.romance.require_kneeling:
        parts.append("the proposer must visibly be kneeling on one knee")

    if cfg.romance.require_ring:
        parts.extend(
            [
                f"the ring is {cfg.romance.ring_style}",
                "the engagement ring must be visible",
            ]
        )

    if cfg.romance.require_flowers:
        parts.append("romantic flowers or bouquet must be visible")

    if brief.third_person_present:
        parts.extend(
            [
                "THREE-PERSON LOVE TRIANGLE",
                "a third woman is present as a real person in the story",
                (f"the third woman is " f"{cfg.romance.third_person_role}"),
                "she is visually separate from the main couple",
                "she watches the proposal from a respectful distance",
                "she is visibly crying",
                "tears are clearly visible on her cheeks",
                "she is quietly sobbing and heartbroken",
                (f"her emotion is " f"{cfg.romance.third_person_emotion}"),
                "she is not a villain",
                "she is not attacking anyone",
                "the main couple remains the visual focus",
            ]
        )

    if brief.proposal_action:
        parts.append(brief.proposal_action)

    if brief.romantic_details:
        parts.append(brief.romantic_details)

    return ", ".join(part.strip() for part in parts if part and part.strip())


def render_prompts(
    brief: Brief,
    cfg: Config,
    characters_block: str = "",
) -> tuple[str, str]:
    """Render final positive and negative SD prompts."""

    fields: dict[str, Any] = brief.model_dump()

    fields["style_modifiers"] = ", ".join(brief.style_modifiers)

    fields["characters"] = characters_block

    positive = cfg.image.positive_template.format(**fields)

    romantic_prompt = _render_romantic_prompt(
        brief,
        cfg,
    )

    if romantic_prompt:
        positive = f"{romantic_prompt}, " f"{positive}"

    negative = cfg.image.negative_template

    positive = re.sub(
        r"(,\s*){2,}",
        ", ",
        positive,
    ).strip(" ,")

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
        '{"subject": "string", "setting": "string", '
        '"lighting": "string", "mood": "string", '
        '"composition": "string", "color_palette": "string", '
        '"time_of_day": "string", '
        '"style_modifiers": ["string", ...]}'
    )

    system = (
        f"{cfg.active_content.system_prompt.strip()} "
        f"Respond ONLY with a JSON object matching this schema exactly: "
        f"{schema}. No prose, no code fences."
    )

    char_section = ""

    if characters_data.get("characters"):
        female = characters_data["characters"].get(
            "female",
            {},
        )

        male = characters_data["characters"].get(
            "male",
            {},
        )

        char_section = (
            "\nRECURRING COUPLE — keep these two people consistent:\n"
            f"Female: {female.get('identity', '')}. "
            f"Features: {female.get('facial_features', '')}. "
            f"Hair: {female.get('hair', '')}. "
            f"Accessories: {female.get('accessories', '')}.\n"
            f"Male: {male.get('identity', '')}. "
            f"Features: {male.get('facial_features', '')}. "
            f"Hair: {male.get('hair', '')}. "
            f"Beard: {male.get('facial_hair', '')}.\n"
        )

    location_section = ""

    if selected_location:
        location_section = (
            "\nLOCATION:\n"
            f"Name: {selected_location.get('name', '')}\n"
            f"Description: {selected_location.get('description', '')}\n"
            f"Lighting: {selected_location.get('lighting', '')}\n"
            f"Mood: {selected_location.get('mood', '')}\n"
        )

    proposal_direction = style.get(
        "proposal_direction",
        "boy_proposes_to_girl",
    )

    if proposal_direction == "boy_proposes_to_girl":
        proposal_section = """
PROPOSAL DIRECTION — BOY PROPOSES TO GIRL.

This direction is mandatory.

The boy is the person proposing.
The boy must kneel on one knee.
The boy must present the girl with a marquise-cut engagement ring.
The ring should be visible.
The boy should give/present flowers.
The girl is receiving the proposal.
The girl should have a sincere emotional reaction.

Do NOT reverse the proposal roles.
Do NOT turn this into a generic standing couple scene.
"""
    else:
        proposal_section = """
PROPOSAL DIRECTION — GIRL PROPOSES TO BOY.

This direction is mandatory.

The girl is the person proposing.
The girl must kneel on one knee.
The girl must present the boy with an engagement ring.
The ring should be visible.
The girl should give/present flowers.
The boy is receiving the proposal.
The boy should have a sincere emotional reaction.

Do NOT reverse the proposal roles.
Do NOT turn this into a generic standing couple scene.
"""

    triangle_section = ""

    if style.get("third_person_present") == "True":
        triangle_section = f"""
LOVE TRIANGLE — THIRD WOMAN PRESENT.

A third woman is part of the emotional story.

She is {cfg.romance.third_person_role}.

She must:
- remain visually separate from the main couple;
- watch the proposal from a respectful distance;
- visibly cry;
- have tears on her cheeks;
- appear to be quietly sobbing;
- communicate heartbreak through her face and body language.

She is not a villain and is not attacking anyone.

Her emotional pain comes from seeing the person she loves choose
someone else.

Third-woman emotion:
{cfg.romance.third_person_emotion}

The main couple remains the visual focus.
"""

    style_section = (
        "\nPHOTOGRAPHIC DIRECTION:\n"
        f"Framing: {style.get('framing', '')}\n"
        f"Interaction: {style.get('interaction', '')}\n"
        f"Emotion: {style.get('emotion', '')}\n"
        f"Composition: {style.get('composition', '')}\n"
        f"Lighting: {style.get('lighting_style', '')}\n"
        f"Color grading: {style.get('color_grading', '')}\n"
        f"Depth of field: {style.get('depth_of_field', '')}\n"
        f"Cinematic style: {style.get('romantic_details', '')}\n"
        "Respect the selected framing and do not default to a generic "
        "centered portrait.\n"
    )

    hints = "\n".join(f"- {key.replace('_', ' ')}: {value}" for key, value in axis_hints.items())

    prev_lines = (
        "\n".join(
            f"- {brief.get('subject', '?')} / " f"{brief.get('mood', '?')}"
            for brief in recent_briefs
        )
        or "(none yet)"
    )

    user = (
        f"Active content profile: {cfg.content.active_profile}\n"
        f"Standing theme: {cfg.active_content.theme}\n"
        f"{char_section}"
        f"{location_section}"
        f"{proposal_section}"
        f"{triangle_section}"
        f"{style_section}\n"
        f"Creative constraints:\n{hints}\n\n"
        "Recent briefs already used. The new scene must be substantially "
        f"different from them:\n{prev_lines}\n\n"
        f"{cfg.active_content.subject_instruction}\n\n"
        "The subject must describe a specific marriage-proposal event. "
        "The pre-selected proposal direction is authoritative and must not "
        "be changed.\n"
        "Make the image feel like a dramatic, emotionally rich, "
        "photorealistic Indian romantic film while remaining tasteful."
    )

    if error_feedback:
        user += (
            f"\n\nPrevious response was invalid: " f"{error_feedback}\n" "Return valid JSON only."
        )

    return [
        {
            "role": "system",
            "content": system,
        },
        {
            "role": "user",
            "content": user,
        },
    ]


def _apply_scene(
    brief: Brief,
    selected_location: dict[str, str] | None,
    style: dict[str, str],
) -> Brief:
    """Stamp deterministic scene metadata."""

    if selected_location:
        brief.location_name = selected_location.get(
            "name",
            "",
        )

        if brief.location_name:
            brief.setting = brief.location_name

        location_lighting = selected_location.get(
            "lighting",
            "",
        )

        if location_lighting:
            brief.lighting = location_lighting

    brief.framing = style.get(
        "framing",
        "",
    )

    brief.proposal_direction = style.get(
        "proposal_direction",
        "",
    )

    brief.proposal_action = style.get(
        "proposal_action",
        "",
    )

    brief.third_person_present = (
        style.get(
            "third_person_present",
            "False",
        )
        == "True"
    )

    brief.third_person_role = style.get(
        "third_person_role",
        "",
    )

    brief.romantic_details = style.get(
        "romantic_details",
        "",
    )

    interaction = style.get(
        "interaction",
        "",
    )

    if brief.proposal_direction == "boy_proposes_to_girl":
        proposal_summary = (
            "boy kneeling and proposing to girl with " "marquise-cut engagement ring and flowers"
        )
    else:
        proposal_summary = "girl kneeling and proposing to boy with " "engagement ring and flowers"

    if brief.third_person_present:
        proposal_summary += (
            ", third woman crying and sobbing from " "unrequited love in the love triangle"
        )

    brief.interaction = f"{interaction}, {proposal_summary}" if interaction else proposal_summary

    return brief


def _fallback_brief(
    cfg: Config,
    axis_hints: dict[str, str],
    seed: int,
    selected_location: dict[str, str] | None,
    style: dict[str, str],
) -> Brief:
    """Create a deterministic proposal brief when Ollama fails."""

    log.warning("using deterministic romantic fallback brief")

    direction = style.get(
        "proposal_direction",
        "boy_proposes_to_girl",
    )

    if direction == "boy_proposes_to_girl":
        subject = (
            "boy kneeling on one knee proposing marriage to the girl, "
            "presenting her with a marquise-cut engagement ring and flowers"
        )
    else:
        subject = (
            "girl kneeling on one knee proposing marriage to the boy, "
            "presenting him with an engagement ring and flowers"
        )

    if style.get("third_person_present") == "True":
        subject += (
            ", while a heartbroken third woman watches from a distance, "
            "crying and quietly sobbing"
        )

    brief = Brief(
        subject=subject,
        setting=cfg.active_content.theme,
        lighting=(
            axis_hints.get(
                "season",
                "soft",
            )
            + " romantic light"
        ),
        mood=(
            style.get(
                "emotion",
                "",
            )
            or "deeply emotional romantic anticipation"
        ),
        composition=(
            style.get(
                "composition",
                "",
            )
            or axis_hints.get(
                "camera_angle",
                "eye-level",
            )
        ),
        color_palette=(
            style.get(
                "color_grading",
                "",
            )
            or "warm cinematic romantic tones"
        ),
        time_of_day=axis_hints.get(
            "time_of_day",
            "golden hour",
        ),
        style_modifiers=[
            axis_hints.get(
                "focal_length",
                "50mm",
            ),
            "cinematic Indian romance",
            "photorealistic",
        ],
    )

    return _apply_scene(
        brief,
        selected_location,
        style,
    )


def extract_location_from_history(
    history_briefs: list[dict[str, Any]],
) -> list[str]:
    """Extract recent location names."""
    locations: list[str] = []

    for brief in history_briefs:
        name = brief.get(
            "location_name",
        )

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
    """Generate a fresh romantic proposal brief."""

    rng = random.Random(
        compute_seed(
            run_date,
            cfg.seed_salt,
        )
        ^ seed
    )

    axis_hints = select_axis_hints(
        rng,
        cfg.brief.axes,
    )

    characters_data = cfg.active_content.visual

    all_locations = flatten_locations(
        characters_data.get(
            "locations",
            {},
        )
    )

    history_locations = extract_location_from_history(recent_briefs)

    selected_location = select_unique_location(
        rng,
        all_locations,
        history_locations,
    )

    style = select_style(
        rng,
        cfg,
        characters_data,
    )

    log.info(
        "axis hints: %s",
        axis_hints,
    )

    log.info(
        "selected proposal direction: %s",
        style.get(
            "proposal_direction",
            "unknown",
        ),
    )

    log.info(
        "third woman present: %s",
        style.get(
            "third_person_present",
            "False",
        ),
    )

    if selected_location:
        log.info(
            "selected location: %s",
            selected_location.get(
                "name",
                "unknown",
            ),
        )

    error_feedback: str | None = None

    for attempt in range(
        1,
        cfg.brief.max_retries + 1,
    ):
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
                seed=seed + attempt,
                temperature=cfg.llm.temperature,
            )

            brief = Brief.model_validate(raw)

        except (
            OllamaError,
            ValidationError,
        ) as exc:
            error_feedback = str(exc)[:300]

            log.warning(
                "brief attempt %d/%d invalid: %s",
                attempt,
                cfg.brief.max_retries,
                error_feedback,
            )

            continue

        if is_near_duplicate(
            brief.subject,
            history_subjects,
            cfg.brief.dedupe_threshold,
        ):
            error_feedback = (
                f"subject '{brief.subject}' is too similar "
                "to a recent post; create a substantially "
                "different proposal scene"
            )

            log.warning(
                "brief attempt %d rejected as near-duplicate",
                attempt,
            )

            continue

        brief = _apply_scene(
            brief,
            selected_location,
            style,
        )

        log.info(
            "brief accepted: %s @ %s | proposal=%s | third_woman=%s",
            brief.subject,
            brief.location_name or "(no location)",
            brief.proposal_direction,
            brief.third_person_present,
        )

        return brief

    return _fallback_brief(
        cfg,
        axis_hints,
        seed,
        selected_location,
        style,
    )
