"""Content-type framework: shared building blocks + registry.

A content type turns a :class:`ProductionContext` (a warmed LLM + image
generator + per-account state and seed) into a :class:`Deliverable` (media +
caption). The heavy lifting — scene generation, image generation, safety gates,
post-processing, captioning — lives here as reusable helpers so photo/reel/
carousel stay tiny and never duplicate the pipeline.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from logging import Logger
from pathlib import Path
from typing import TYPE_CHECKING, Protocol

from ..caption import (
    CaptionResult,
    OllamaClient,
    compose_final_caption,
    generate_caption,
    load_banned_hashtags,
)
from ..config import Config, Secrets
from ..imagegen import GeneratedImage, ImageGenerator
from ..overlay import plan_slide, typeset
from ..postproc import ASPECT_DIMS, ProcessedImage, center_crop_to_aspect, process_image
from ..safety import SafetyError, load_profanity, run_caption_gates, run_image_gates
from ..scene import (
    Brief,
    build_character_block,
    generate_brief,
    profile_kind,
    random_brief,
    random_theme_active,
    render_prompts,
    vary_framing,
)
from ..state import State

if TYPE_CHECKING:
    pass


class ExitCode:
    OK = 0
    CONFIG = 1
    BRIEF = 2
    IMAGE = 3
    POSTPROC = 4
    CAPTION = 5
    SAFETY = 6
    POST = 7
    DUPLICATE = 8


class ContentError(Exception):
    """A content-production failure carrying the pipeline exit code to return."""

    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- #
# Data carriers
# --------------------------------------------------------------------------- #


@dataclass
class SceneResult:
    """One fully rendered image scene (brief -> gated, post-processed JPEG)."""

    brief: Brief
    positive: str
    negative: str
    generated: GeneratedImage
    processed: ProcessedImage


@dataclass
class Deliverable:
    """What a content type produces for the orchestrator to publish + record."""

    kind: str  # "photo" | "reel" | "carousel"
    media: list[Path]  # 1 image=photo, 1 mp4=reel, N images=carousel
    primary: SceneResult  # first scene — drives artifacts, idempotency, record
    caption: str | None = None  # composed final caption (None in image-only)
    alt_text: str | None = None
    hashtags: list[str] = field(default_factory=list)
    comment_text: str | None = None
    scene_descs: list[str] = field(default_factory=list)


@dataclass
class ProductionContext:
    """Everything a content type needs, warmed once and shared across scenes."""

    cfg: Config
    secrets: Secrets
    ollama: OllamaClient
    gen: ImageGenerator
    state: State
    seed: int
    run_date: str
    stamp: str
    out_dir: Path
    llm_model: str
    image_only: bool
    log: Logger

    @property
    def characters_block(self) -> str:
        return build_character_block(self.cfg)


class ContentType(Protocol):
    name: str

    def produce(self, ctx: ProductionContext) -> Deliverable: ...


# --------------------------------------------------------------------------- #
# Registry + weighted selection
# --------------------------------------------------------------------------- #

REGISTRY: dict[str, type[ContentType]] = {}


def register(cls: type[ContentType]) -> type[ContentType]:
    """Class decorator that registers a content type under its ``name``."""
    REGISTRY[cls.name] = cls
    return cls


def select_content_type(content_mix: dict[str, int], rng: random.Random) -> ContentType:
    """Weighted-random pick of a registered content type from a mix.

    ``content_mix`` maps a content-type name to a non-negative integer weight.
    Unknown or unregistered names are ignored; an empty/zero mix falls back to
    an even choice over every registered type.
    """
    weighted = {k: v for k, v in content_mix.items() if k in REGISTRY and v > 0}
    if not weighted:
        weighted = {k: 1 for k in REGISTRY}
    names = sorted(weighted)  # sorted -> deterministic for a fixed seed
    weights = [weighted[n] for n in names]
    chosen = rng.choices(names, weights=weights, k=1)[0]
    return REGISTRY[chosen]()


def content_type_by_name(name: str) -> ContentType:
    cls = REGISTRY.get(name)
    if cls is None:
        raise ContentError(ExitCode.CONFIG, f"unknown content type: {name!r}")
    return cls()


# --------------------------------------------------------------------------- #
# Shared production helpers
# --------------------------------------------------------------------------- #


def generate_scene(
    ctx: ProductionContext,
    seed: int,
    out_path: Path,
    recent_subjects: list[str],
    recent_briefs: list[dict],
    check_dupe: bool = False,
    slide_total: int = 1,
) -> SceneResult:
    """Run one full image scene: brief -> image -> gates -> post-process.

    Raises :class:`ContentError` (with the right exit code) on brief/image/
    postproc failure and on a duplicate primary image; lets :class:`SafetyError`
    propagate so the orchestrator can map it to the SAFETY exit code.
    """
    try:
        brief = (
            random_brief(ctx.cfg, recent_subjects)
            if random_theme_active(ctx.cfg)
            else generate_brief(
                client=ctx.ollama,
                cfg=ctx.cfg,
                seed=seed,
                run_date=ctx.run_date,
                history_subjects=recent_subjects,
                recent_briefs=recent_briefs,
                model=ctx.llm_model,
            )
        )
    except Exception as exc:  # noqa: BLE001
        raise ContentError(ExitCode.BRIEF, f"brief generation failed: {exc}") from exc

    scene = _render_scene(ctx, brief, seed, out_path, slide_total=slide_total)
    if check_dupe and ctx.state.has_image_hash(scene.processed.sha256):
        raise ContentError(
            ExitCode.DUPLICATE,
            f"image hash {scene.processed.sha256[:12]} already posted; refusing to repeat",
        )
    return scene


def _render_scene(
    ctx: ProductionContext,
    brief: Brief,
    seed: int,
    out_path: Path,
    slide_index: int = 0,
    slide_total: int = 1,
    reuse: GeneratedImage | None = None,
) -> SceneResult:
    """Render one image from an already-built brief: prompt -> image -> gates ->
    post-process. No LLM call — used for extra reel/carousel scenes so a
    multi-scene deliverable needs only ONE brief (a big CPU-time saving)."""
    positive, negative = render_prompts(brief, ctx.cfg, characters_block=ctx.characters_block)
    ctx.log.info("positive prompt: %s", positive)
    if reuse is not None:
        generated = reuse  # already generated and gated (infographic slides)
    else:
        try:
            generated = ctx.gen.generate(positive, negative, seed)
        except Exception as exc:  # noqa: BLE001
            raise ContentError(ExitCode.IMAGE, f"image generation failed: {exc}") from exc
        run_image_gates(generated.image, ctx.cfg)  # SafetyError propagates
    image = generated.image
    if profile_kind(ctx.cfg) == "infographic" and brief.headline:
        # Typeset at final resolution so text is sharp and never cropped.
        image = typeset(
            center_crop_to_aspect(image, *ASPECT_DIMS[ctx.cfg.postproc.aspect]),
            plan_slide(brief.headline, brief.points, slide_index, slide_total),
        )
    try:
        processed = process_image(image, ctx.cfg, out_path)
    except Exception as exc:  # noqa: BLE001
        raise ContentError(ExitCode.POSTPROC, f"post-processing failed: {exc}") from exc
    return SceneResult(
        brief=brief, positive=positive, negative=negative, generated=generated, processed=processed
    )


def generate_scenes(ctx: ProductionContext, num_scenes: int) -> list[SceneResult]:
    """Generate ``num_scenes`` coherent scenes of the same moment.

    ONE LLM brief is generated (deduped against history); extra scenes reuse it
    with a re-rolled framing/shot and a fresh image seed, so the couple, location
    and action stay coherent while the composition varies — and we pay for only
    one (slow) LLM brief per reel/carousel. A scene that fails is skipped (never
    fatal); the deliverable uses whatever succeeded (>=1).
    """
    recent_subjects = ctx.state.recent_subjects(ctx.cfg.brief.history_depth)
    recent_briefs = ctx.state.recent_briefs(ctx.cfg.brief.history_depth)

    if profile_kind(ctx.cfg) == "infographic":
        return _infographic_slides(ctx, num_scenes, recent_subjects, recent_briefs)

    primary = generate_scene(
        ctx,
        ctx.seed,
        ctx.out_dir / f"{ctx.stamp}.jpg",
        recent_subjects=recent_subjects,
        recent_briefs=recent_briefs,
        check_dupe=True,
        slide_total=max(1, num_scenes),
    )
    scenes = [primary]

    for i in range(1, max(1, num_scenes)):
        scene_seed = ctx.seed + i * 7919
        variant = (
            random_brief(ctx.cfg, recent_subjects)
            if random_theme_active(ctx.cfg)
            else vary_framing(primary.brief, scene_seed)
        )
        try:
            scenes.append(
                _render_scene(
                    ctx,
                    variant,
                    scene_seed,
                    ctx.out_dir / f"{ctx.stamp}_{i}.jpg",
                    slide_index=i,
                    slide_total=max(1, num_scenes),
                )
            )
        except (ContentError, SafetyError) as exc:
            ctx.log.warning("scene %d skipped (%s); continuing", i, exc)
    return scenes


# Instagram's carousel limit.
_MAX_SLIDES = 10


def _infographic_slides(
    ctx: ProductionContext,
    num_scenes: int,
    recent_subjects: list[str],
    recent_briefs: list[dict],
) -> list[SceneResult]:
    """One background, N typeset slides: headline, one per takeaway, recap.

    Renders the diffusion image ONCE (the dominant CPU cost) and reuses it, so
    a carousel can carry every takeaway and keeps a consistent template look.
    """
    first = generate_scene(
        ctx,
        ctx.seed,
        ctx.out_dir / f"{ctx.stamp}.jpg",
        recent_subjects=recent_subjects,
        recent_briefs=recent_briefs,
        check_dupe=True,
        slide_total=1,
    )
    brief = first.brief
    if not brief.headline or num_scenes <= 1:
        return [first]
    total = min(_MAX_SLIDES, max(num_scenes, 1 + len(brief.points)))
    return [
        _render_scene(
            ctx,
            brief,
            ctx.seed,
            ctx.out_dir / (f"{ctx.stamp}.jpg" if i == 0 else f"{ctx.stamp}_{i}.jpg"),
            slide_index=i,
            slide_total=total,
            reuse=first.generated,
        )
        for i in range(total)
    ]


@dataclass
class CaptionBundle:
    caption: str
    comment_text: str | None
    alt_text: str
    hashtags: list[str]


def build_caption(ctx: ProductionContext, brief: Brief) -> CaptionBundle:
    """Generate + gate + compose the final caption for a brief."""
    try:
        banned = load_banned_hashtags()
        result: CaptionResult = generate_caption(
            client=ctx.ollama,
            brief=brief,
            cfg=ctx.cfg,
            seed=ctx.seed,
            model=ctx.llm_model,
            banned=banned,
        )
    except Exception as exc:  # noqa: BLE001
        raise ContentError(ExitCode.CAPTION, f"caption generation failed: {exc}") from exc

    run_caption_gates(result.caption, ctx.cfg, load_profanity())  # SafetyError propagates

    try:
        if ctx.cfg.caption.hashtag_placement == "caption":
            final_caption = compose_final_caption(result.caption, result.hashtags, ctx.cfg)
            comment_text: str | None = None
        else:
            final_caption = compose_final_caption(result.caption, [], ctx.cfg)
            comment_text = " ".join(result.hashtags) if result.hashtags else None
    except ValueError as exc:
        raise ContentError(ExitCode.CAPTION, f"caption length error: {exc}") from exc

    return CaptionBundle(
        caption=final_caption,
        comment_text=comment_text,
        alt_text=result.alt_text,
        hashtags=result.hashtags,
    )
