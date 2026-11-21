"""Multi-image carousel (album) post.

Generates several diverging scenes of the same characters and posts them as one
swipeable album. If only one scene survives, the poster naturally publishes it
as a single photo. A relatable verse is drawn in the same spot on every slide.
"""

from __future__ import annotations

from .base import (
    Deliverable,
    ProductionContext,
    build_caption,
    choose_poem,
    generate_scene,
    generate_scenes,
    register,
    stamp_poem,
)


@register
class Carousel:
    name = "carousel"

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
            poem = choose_poem(ctx, scene.brief)
            stamp_poem(ctx, [scene.processed.path], poem)
            return Deliverable(
                kind="carousel",
                media=[scene.processed.path],
                primary=scene,
                scene_descs=[scene.brief.subject],
                poem=poem.as_record() if poem else None,
            )

        scenes = generate_scenes(ctx, ctx.cfg.carousel.num_slides)
        # Same verse, same position on every slide, so it stays put as you swipe.
        poem = choose_poem(ctx, scenes[0].brief)
        stamp_poem(ctx, [s.processed.path for s in scenes], poem)
        cap = build_caption(ctx, scenes[0].brief, poem)
        return Deliverable(
            kind="carousel",
            media=[s.processed.path for s in scenes],
            primary=scenes[0],
            caption=cap.caption,
            alt_text=cap.alt_text,
            hashtags=cap.hashtags,
            comment_text=cap.comment_text,
            scene_descs=[s.brief.subject for s in scenes],
            poem=poem.as_record() if poem else None,
        )
