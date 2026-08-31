"""Multi-scene vertical Reel.

Generates several diverging scenes of the same characters, optionally animates
selected scenes with an AI image-to-video provider, and assembles the result
into a 1080x1920 MP4 with music. Any failure to build the video falls back to
posting the first still image (never fatal).
"""

from __future__ import annotations

from pathlib import Path

from .base import (
    Deliverable,
    ProductionContext,
    build_caption,
    generate_scene,
    generate_scenes,
    register,
)


def _assemble_reel(
    ctx: ProductionContext,
    scene_paths: list[Path],
    scene_descs: list[str],
) -> Path:
    """Assemble a Reel MP4 (AI motion when available, else FFmpeg Ken Burns).

    Falls back to the first still image on any renderer failure.
    """
    from ..render.reel import ReelError, assemble_ai_clips, build_reel

    cfg, stamp, seed, log = ctx.cfg, ctx.stamp, ctx.seed, ctx.log
    out_dir = ctx.out_dir

    ai_clips: list[Path] = []
    av = cfg.reel.ai_video
    if av.enabled and av.mode == "auto":
        from ..render.ai_video import AIVideoError, generate_ai_video
        from ..render.image_host import ImageHostError, publish_image_to_github_release

        # PixVerse needs a public image URL (hosted via GitHub Release); HF POSTs
        # the bytes directly. Any failure is non-fatal — FFmpeg motion is used.
        needs_url = av.provider.lower() == "pixverse"
        for idx in av.ai_scene_indexes:
            if idx >= len(scene_paths):
                continue
            still = scene_paths[idx]
            desc = scene_descs[idx] if idx < len(scene_descs) else cfg.active_content.theme
            try:
                url = (
                    publish_image_to_github_release(still, tag=f"autogram-reel-{stamp}")
                    if needs_url
                    else None
                )
                clip = generate_ai_video(
                    still, desc, cfg, out_dir / f"{stamp}_ai{idx}.mp4", image_url=url
                )
                ai_clips.append(clip)
            except (AIVideoError, ImageHostError) as exc:
                log.warning("AI video scene %d unavailable (%s); using FFmpeg motion", idx, exc)

    try:
        if ai_clips:
            path = assemble_ai_clips(ai_clips, cfg, out_dir / f"{stamp}.mp4", seed)
            log.info("reel assembled from %d AI clip(s)", len(ai_clips))
        else:
            path = build_reel(scene_paths, cfg, out_dir / f"{stamp}.mp4", seed)
            log.info("reel assembled from %d still scene(s)", len(scene_paths))
        return path
    except ReelError as exc:
        log.warning("reel unavailable (%s); posting the still image instead", exc)
        return scene_paths[0]


@register
class Reel:
    name = "reel"

    def produce(self, ctx: ProductionContext) -> Deliverable:
        if ctx.image_only:
            scene = generate_scene(
                ctx,
                ctx.seed,
                ctx.out_dir / f"{ctx.stamp}.jpg",
                recent_subjects=ctx.state.recent_subjects(ctx.cfg.brief.history_depth),
                recent_briefs=ctx.state.recent_briefs(ctx.cfg.brief.history_depth),
                check_dupe=True,
            )
            return Deliverable(
                kind="reel",
                media=[scene.processed.path],
                primary=scene,
                scene_descs=[scene.brief.subject],
            )

        scenes = generate_scenes(ctx, ctx.cfg.reel.num_scenes)
        scene_paths = [s.processed.path for s in scenes]
        scene_descs = [s.brief.subject for s in scenes]
        cap = build_caption(ctx, scenes[0].brief)
        publish_path = _assemble_reel(ctx, scene_paths, scene_descs)
        return Deliverable(
            kind="reel",
            media=[publish_path],
            primary=scenes[0],
            caption=cap.caption,
            alt_text=cap.alt_text,
            hashtags=cap.hashtags,
            comment_text=cap.comment_text,
            scene_descs=scene_descs,
        )
