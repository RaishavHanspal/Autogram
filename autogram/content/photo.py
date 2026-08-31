"""Single-image photo post."""

from __future__ import annotations

from .base import (
    Deliverable,
    ProductionContext,
    build_caption,
    generate_scene,
    register,
)


@register
class PhotoPost:
    name = "photo"

    def produce(self, ctx: ProductionContext) -> Deliverable:
        scene = generate_scene(
            ctx,
            ctx.seed,
            ctx.out_dir / f"{ctx.stamp}.jpg",
            recent_subjects=ctx.state.recent_subjects(ctx.cfg.brief.history_depth),
            recent_briefs=ctx.state.recent_briefs(ctx.cfg.brief.history_depth),
            check_dupe=True,
        )
        cap = None if ctx.image_only else build_caption(ctx, scene.brief)
        return Deliverable(
            kind="photo",
            media=[scene.processed.path],
            primary=scene,
            caption=cap.caption if cap else None,
            alt_text=cap.alt_text if cap else None,
            hashtags=cap.hashtags if cap else [],
            comment_text=cap.comment_text if cap else None,
            scene_descs=[scene.brief.subject],
        )
