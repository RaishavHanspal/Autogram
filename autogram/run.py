"""Orchestration CLI: theme -> brief -> image -> postproc -> caption -> post.

Distinct non-zero exit codes per failure class (see ExitCode). Structured
logging with per-stage timing. Honors --dry-run, --image-only, --seed,
--description.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .brief import (
    Brief,
    build_character_block,
    compute_seed,
    generate_brief,
    load_characters_data,
    render_prompts,
)
from .caption import (
    OllamaClient,
    compose_final_caption,
    generate_caption,
    load_banned_hashtags,
)
from .config import Config, Secrets, load_config, load_secrets
from .imagegen import ImageGenerator
from .logging_utils import get_logger, setup_logging, stage_timer
from .postproc import ProcessedImage, process_image
from .safety import SafetyError, load_profanity, run_caption_gates, run_image_gates
from .state import State


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


class PipelineError(Exception):
    def __init__(self, code: int, message: str) -> None:
        super().__init__(message)
        self.code = code


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="autogram", description="Self-hosted Instagram auto-poster.")
    p.add_argument("--description", help="One-off override of the standing theme.")
    p.add_argument("--dry-run", action="store_true", help="Run everything, post nothing.")
    p.add_argument("--image-only", action="store_true", help="Skip caption and posting.")
    p.add_argument("--seed", type=int, help="Reproducible run seed.")
    p.add_argument("--config", default=None, help="Path to config.yaml.")
    p.add_argument("--log-level", default="INFO", help="DEBUG/INFO/WARNING/ERROR.")
    p.add_argument("--version", action="version", version=f"autogram {__version__}")
    return p.parse_args(argv)


def _llm_model(cfg: Config) -> str:
    """Auto-select the LLM: hq model on a GPU host, default on CPU."""
    try:
        import torch

        if torch.cuda.is_available():
            return cfg.llm.hq_model
    except Exception:  # noqa: BLE001 - torch optional at this layer
        pass
    return cfg.llm.model


def _write_artifacts(
    out_dir: Path,
    stamp: str,
    brief: Brief,
    positive: str,
    negative: str,
    processed: ProcessedImage,
    final_caption: str | None,
    alt_text: str | None,
    hashtags: list[str] | None,
) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    payload: dict[str, Any] = {
        "brief": brief.model_dump(),
        "positive_prompt": positive,
        "negative_prompt": negative,
        "image": str(processed.path),
        "image_sha256": processed.sha256,
    }
    if final_caption is not None:
        payload["caption"] = final_caption
        payload["alt_text"] = alt_text
        payload["hashtags"] = hashtags
        (out_dir / f"{stamp}.txt").write_text(final_caption, encoding="utf-8")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def run_pipeline(args: argparse.Namespace, cfg: Config, secrets: Secrets) -> int:
    log = get_logger("run")
    now = datetime.now(UTC)
    run_date = now.strftime("%Y-%m-%d")
    stamp = now.strftime("%Y%m%dT%H%M%SZ")

    if args.description:
        cfg.theme = args.description
        log.info("theme overridden via --description")

    # Seed from the per-second run stamp (not the calendar day) so repeated runs
    # — the schedule fires several times a day — never reuse a seed and never
    # regenerate an identical image. --seed still forces full reproducibility.
    seed = args.seed if args.seed is not None else compute_seed(stamp, cfg.seed_salt)
    log.info(
        "run seed=%d date=%s stamp=%s dry_run=%s image_only=%s",
        seed,
        run_date,
        stamp,
        args.dry_run,
        args.image_only,
    )

    state = State(cfg.state.history_path)
    out_dir = Path(cfg.state.out_dir)
    image_path = out_dir / f"{stamp}.jpg"

    llm_model = _llm_model(cfg)

    # --- brief (needs the LLM) ---
    host = getattr(secrets, "OLLAMA_HOST", "http://127.0.0.1:11434")
    with OllamaClient(host, cfg.llm.ready_timeout_s, cfg.llm.request_timeout_s) as ollama:
        try:
            with stage_timer(log, "ollama"):
                ollama.ensure_running()
                ollama.ensure_model(llm_model)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(ExitCode.BRIEF, f"LLM runtime unavailable: {exc}") from exc

        try:
            with stage_timer(log, "brief"):
                brief = generate_brief(
                    client=ollama,
                    cfg=cfg,
                    seed=seed,
                    run_date=run_date,
                    history_subjects=state.recent_subjects(cfg.brief.history_depth),
                    recent_briefs=state.recent_briefs(cfg.brief.history_depth),
                    model=llm_model,
                )
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(ExitCode.BRIEF, f"brief generation failed: {exc}") from exc

        # Inject the fixed couple description directly into the image prompt so
        # the SAME characters appear every time, independent of the LLM.
        characters_block = build_character_block(load_characters_data())
        positive, negative = render_prompts(brief, cfg, characters_block=characters_block)
        log.info("positive prompt: %s", positive)

        # --- image ---
        try:
            with stage_timer(log, "imagegen"):
                gen = ImageGenerator(cfg)
                generated = gen.generate(positive, negative, seed)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(ExitCode.IMAGE, f"image generation failed: {exc}") from exc

        # --- image safety gates ---
        try:
            with stage_timer(log, "safety.image"):
                run_image_gates(generated.image, cfg)
        except SafetyError as exc:
            raise PipelineError(ExitCode.SAFETY, f"[{exc.gate}] {exc}") from exc

        # --- post-processing ---
        try:
            with stage_timer(log, "postproc"):
                processed = process_image(generated.image, cfg, image_path)
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(ExitCode.POSTPROC, f"post-processing failed: {exc}") from exc

        # --- idempotency ---
        if state.has_image_hash(processed.sha256):
            raise PipelineError(
                ExitCode.DUPLICATE,
                f"image hash {processed.sha256[:12]} already posted; refusing to repeat",
            )

        # --- extra Reel scenes (same couple, different places) ---
        # Reuse the already-loaded pipeline (gen) so the model loads once. Each
        # scene diverges via history + a distinct seed. A failed scene is skipped,
        # never fatal — the Reel just uses whatever scenes succeeded (>=1).
        reel_scene_paths: list[Path] = [processed.path]
        reel_scene_descs: list[str] = [brief.subject]
        if cfg.reel.enabled and not args.image_only and cfg.reel.num_scenes > 1:
            acc_briefs = state.recent_briefs(cfg.brief.history_depth) + [brief.model_dump()]
            acc_subjects = state.recent_subjects(cfg.brief.history_depth) + [brief.subject]
            for i in range(1, cfg.reel.num_scenes):
                scene_seed = seed + i * 7919
                try:
                    with stage_timer(log, f"reel.scene{i}"):
                        b_i = generate_brief(
                            client=ollama,
                            cfg=cfg,
                            seed=scene_seed,
                            run_date=run_date,
                            history_subjects=acc_subjects,
                            recent_briefs=acc_briefs,
                            model=llm_model,
                        )
                        pos_i, neg_i = render_prompts(b_i, cfg, characters_block=characters_block)
                        g_i = gen.generate(pos_i, neg_i, scene_seed)
                        run_image_gates(g_i.image, cfg)
                        p_i = process_image(g_i.image, cfg, out_dir / f"{stamp}_{i}.jpg")
                    reel_scene_paths.append(p_i.path)
                    reel_scene_descs.append(b_i.subject)
                    acc_briefs.append(b_i.model_dump())
                    acc_subjects.append(b_i.subject)
                except Exception as exc:  # noqa: BLE001
                    log.warning("reel scene %d skipped (%s); continuing", i, exc)

        # --- image-only exit ---
        if args.image_only:
            _write_artifacts(out_dir, stamp, brief, positive, negative, processed, None, None, None)
            _record(
                state,
                stamp,
                now,
                brief,
                positive,
                negative,
                generated,
                processed,
                None,
                None,
                [],
                secrets.POST_BACKEND,
                None,
                "image-only",
            )
            log.info("image-only complete: %s", processed.path)
            return ExitCode.OK

        # --- caption ---
        try:
            with stage_timer(log, "caption"):
                banned = load_banned_hashtags()
                caption_result = generate_caption(
                    client=ollama, brief=brief, cfg=cfg, seed=seed, model=llm_model, banned=banned
                )
        except Exception as exc:  # noqa: BLE001
            raise PipelineError(ExitCode.CAPTION, f"caption generation failed: {exc}") from exc

    # --- caption safety gate (ollama no longer needed) ---
    try:
        with stage_timer(log, "safety.caption"):
            run_caption_gates(caption_result.caption, cfg, load_profanity())
    except SafetyError as exc:
        raise PipelineError(ExitCode.SAFETY, f"[{exc.gate}] {exc}") from exc

    # --- compose final caption per placement ---
    try:
        if cfg.caption.hashtag_placement == "caption":
            final_caption = compose_final_caption(
                caption_result.caption, caption_result.hashtags, cfg
            )
            comment_text: str | None = None
        else:
            final_caption = compose_final_caption(caption_result.caption, [], cfg)
            comment_text = " ".join(caption_result.hashtags) if caption_result.hashtags else None
    except ValueError as exc:
        raise PipelineError(ExitCode.CAPTION, f"caption length error: {exc}") from exc

    _write_artifacts(
        out_dir,
        stamp,
        brief,
        positive,
        negative,
        processed,
        final_caption,
        caption_result.alt_text,
        caption_result.hashtags,
    )

    # --- optional Reel assembly (posted via the SAME publish path) ---
    publish_path: Path = processed.path
    if cfg.reel.enabled:
        from .reel import ReelError, assemble_ai_clips, build_reel

        # Try real AI motion for the configured scene indexes. Any failure (no
        # key, no credits, timeout) is non-fatal — we fall back to the FFmpeg
        # reel. PixVerse needs a public image URL (hosted via GitHub Release);
        # Hugging Face POSTs the image bytes directly, so no hosting is needed.
        ai_clips: list[Path] = []
        av = cfg.reel.ai_video
        if av.enabled and av.mode == "auto":
            from .ai_video import AIVideoError, generate_ai_video
            from .image_host import ImageHostError, publish_image_to_github_release

            needs_url = av.provider.lower() == "pixverse"
            for idx in av.ai_scene_indexes:
                if idx >= len(reel_scene_paths):
                    continue
                still = reel_scene_paths[idx]
                desc = reel_scene_descs[idx] if idx < len(reel_scene_descs) else cfg.theme
                try:
                    with stage_timer(log, f"ai_video.scene{idx}"):
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
            with stage_timer(log, "reel"):
                if ai_clips:
                    publish_path = assemble_ai_clips(ai_clips, cfg, out_dir / f"{stamp}.mp4", seed)
                    log.info("reel assembled from %d AI clip(s)", len(ai_clips))
                else:
                    publish_path = build_reel(reel_scene_paths, cfg, out_dir / f"{stamp}.mp4", seed)
                    log.info("reel assembled from %d still scene(s)", len(reel_scene_paths))
        except ReelError as exc:
            log.warning("reel unavailable (%s); posting the still image instead", exc)
            publish_path = processed.path

    # --- publish ---
    from .poster import PosterError, build_poster

    try:
        with stage_timer(log, "post"):
            poster = build_poster(secrets, cfg, dry_run=args.dry_run)
            result = poster.publish(publish_path, final_caption, caption_result.alt_text)
            if comment_text and result.post_id and result.post_id != "dry-run":
                poster.comment(result.post_id, comment_text)
            elif comment_text and args.dry_run:
                poster.comment("dry-run", comment_text)
    except PosterError as exc:
        raise PipelineError(ExitCode.POST, f"publish failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise PipelineError(ExitCode.POST, f"publish failed unexpectedly: {exc}") from exc

    _record(
        state,
        stamp,
        now,
        brief,
        positive,
        negative,
        generated,
        processed,
        final_caption,
        caption_result.alt_text,
        caption_result.hashtags,
        result.backend,
        result,
        "dry-run" if result.dry_run else "posted",
    )
    log.info(
        "done. backend=%s post_id=%s url=%s dry_run=%s",
        result.backend,
        result.post_id,
        result.url,
        result.dry_run,
    )
    return ExitCode.OK


def _record(
    state: State,
    stamp: str,
    now: datetime,
    brief: Brief,
    positive: str,
    negative: str,
    generated: Any,
    processed: ProcessedImage,
    caption: str | None,
    alt_text: str | None,
    hashtags: list[str],
    backend: str,
    result: Any,
    status: str,
) -> None:
    record = {
        "stamp": stamp,
        "timestamp": now.isoformat(),
        "brief": brief.model_dump(),
        "positive_prompt": positive,
        "negative_prompt": negative,
        "seed": generated.meta.seed,
        "image_model": generated.meta.model_id,
        "device": generated.meta.device,
        "image_sha256": processed.sha256,
        "image_path": str(processed.path),
        "caption": caption,
        "alt_text": alt_text,
        "hashtags": hashtags,
        "backend": backend,
        "post_id": getattr(result, "post_id", None),
        "post_url": getattr(result, "url", None),
        "status": status,
    }
    state.append(record)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    log = get_logger("run")
    try:
        cfg = load_config(args.config)
        secrets = load_secrets()
    except Exception as exc:  # noqa: BLE001
        log.error("configuration error: %s", exc)
        return ExitCode.CONFIG

    try:
        return run_pipeline(args, cfg, secrets)
    except PipelineError as exc:
        log.error("pipeline failed (exit %d): %s", exc.code, exc)
        return exc.code
    except KeyboardInterrupt:
        log.error("interrupted")
        return ExitCode.CONFIG


if __name__ == "__main__":
    sys.exit(main())
