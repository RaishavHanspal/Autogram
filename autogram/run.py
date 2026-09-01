"""Orchestration CLI.

For each enabled account: pick a content type (photo / reel / carousel) from the
account's content mix, produce it (brief -> image(s) -> gates -> post-process ->
caption), then publish it via the account's backend and record history. The LLM
and image model are warmed once and reused across every account and scene.

Distinct non-zero exit codes per failure class (see ExitCode). A per-account
failure is logged and does not abort the other accounts; the process exits with
the worst account's code. Honors --dry-run, --image-only, --seed, --description,
--account, --content-type, --content-profile.
"""

from __future__ import annotations

import argparse
import json
import os
import random
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from . import __version__
from .caption import OllamaClient
from .config import AccountConfig, Config, Secrets, load_config, load_secrets
from .content import (
    ContentError,
    Deliverable,
    ExitCode,
    ProductionContext,
    select_content_type,
)
from .content.base import content_type_by_name
from .imagegen import ImageGenerator
from .logging_utils import get_logger, setup_logging, stage_timer
from .safety import SafetyError
from .scene import compute_seed
from .state import State

log = get_logger("run")


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="autogram", description="Self-hosted social auto-poster.")
    p.add_argument("--description", help="One-off override of the active profile theme.")
    p.add_argument("--content-profile", help="Force a named content profile for all accounts.")
    p.add_argument("--content-type", help="Force a content type (photo|reel|carousel).")
    p.add_argument("--account", help="Run only the account with this id.")
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


# --------------------------------------------------------------------------- #
# Accounts + credentials
# --------------------------------------------------------------------------- #


def _account_from_entry(cfg: Config, entry: dict[str, Any]) -> AccountConfig:
    """Build an account from an AUTOGRAM_ACCOUNTS JSON entry (secret-only setup)."""
    raw_mix = entry.get("content_mix")
    mix = {str(k): int(v) for k, v in raw_mix.items()} if isinstance(raw_mix, dict) else {}
    return AccountConfig(
        id=str(entry["id"]),
        platform=str(entry.get("platform", "instagram")),
        backend=str(entry.get("backend", "")),
        profile=str(entry.get("profile", "")),
        enabled=bool(entry.get("enabled", True)),
        content_mix=mix,
        audio_dir=str(entry.get("audio_dir", "")),
    )


def _effective_accounts(
    cfg: Config,
    secrets: Secrets,
    only_id: str | None,
    accounts_json: dict[str, dict[str, Any]],
) -> list[AccountConfig]:
    """Resolve the accounts to run.

    Precedence: accounts declared in config.yaml win; otherwise each
    AUTOGRAM_ACCOUNTS entry BECOMES an account (so a secret alone is enough to
    configure accounts); otherwise a single implicit account from the flat env.
    """
    declared = [a for a in cfg.accounts if a.enabled]
    if declared:
        accounts = declared
    elif accounts_json:
        accounts = [_account_from_entry(cfg, e) for e in accounts_json.values()]
        accounts = [a for a in accounts if a.enabled]
    else:
        accounts = [
            AccountConfig(
                id="default",
                backend=(secrets.POST_BACKEND or "instagrapi"),
                profile=cfg.content.active_profile,
            )
        ]
    if only_id:
        accounts = [a for a in accounts if a.id == only_id]
    return accounts


def _infer_backend(creds: dict[str, str | None], platform: str) -> str:
    """Pick a backend from whichever credentials are present.

    ig_access_token/ig_user_id -> graph (official API); ig_username ->
    instagrapi; youtube_* -> youtube. Lets a credentials-only account (no
    explicit backend) route itself correctly.
    """
    if (
        platform == "youtube"
        or creds.get("youtube_refresh_token")
        or creds.get("youtube_client_id")
    ):
        return "youtube"
    if creds.get("ig_access_token") or creds.get("ig_user_id"):
        return "graph"
    if creds.get("ig_username"):
        return "instagrapi"
    return "instagrapi"


def _load_accounts_json(secrets: Secrets) -> dict[str, dict[str, Any]]:
    raw = secrets.AUTOGRAM_ACCOUNTS or os.getenv("AUTOGRAM_ACCOUNTS")
    if not raw:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        log.warning("AUTOGRAM_ACCOUNTS is not valid JSON (%s); ignoring", exc)
        return {}
    result: dict[str, dict[str, Any]] = {}
    if isinstance(data, list):
        for entry in data:
            if isinstance(entry, dict) and entry.get("id"):
                result[str(entry["id"])] = entry
    return result


def _creds_for(
    account: AccountConfig,
    accounts_json: dict[str, dict[str, Any]],
    secrets: Secrets,
) -> dict[str, str | None]:
    """Per-account credentials from AUTOGRAM_ACCOUNTS, falling back to flat env."""
    entry = accounts_json.get(account.id, {})

    def pick(key: str, flat: str | None) -> str | None:
        val = entry.get(key)
        return str(val) if val else flat

    return {
        "ig_username": pick("ig_username", secrets.IG_USERNAME),
        "ig_password": pick("ig_password", secrets.IG_PASSWORD),
        "ig_session_b64": pick("ig_session_b64", secrets.IG_SESSION_B64),
        "ig_proxy": pick("ig_proxy", secrets.IG_PROXY),
        "ig_access_token": pick("ig_access_token", secrets.IG_ACCESS_TOKEN),
        "ig_user_id": pick("ig_user_id", secrets.IG_USER_ID),
        "youtube_client_id": pick("youtube_client_id", secrets.YOUTUBE_CLIENT_ID),
        "youtube_client_secret": pick("youtube_client_secret", secrets.YOUTUBE_CLIENT_SECRET),
        "youtube_refresh_token": pick("youtube_refresh_token", secrets.YOUTUBE_REFRESH_TOKEN),
        "github_token": secrets.GITHUB_TOKEN,
        "github_repository": secrets.GITHUB_REPOSITORY,
    }


# --------------------------------------------------------------------------- #
# Artifacts + history
# --------------------------------------------------------------------------- #


def _write_artifacts(out_dir: Path, stamp: str, deliverable: Deliverable) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    primary = deliverable.primary
    payload: dict[str, Any] = {
        "kind": deliverable.kind,
        "brief": primary.brief.model_dump(),
        "positive_prompt": primary.positive,
        "negative_prompt": primary.negative,
        "media": [str(m) for m in deliverable.media],
        "image_sha256": primary.processed.sha256,
        "scene_descs": deliverable.scene_descs,
    }
    if deliverable.caption is not None:
        payload["caption"] = deliverable.caption
        payload["alt_text"] = deliverable.alt_text
        payload["hashtags"] = deliverable.hashtags
        (out_dir / f"{stamp}.txt").write_text(deliverable.caption, encoding="utf-8")
    (out_dir / f"{stamp}.json").write_text(
        json.dumps(payload, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def _record(
    state: State,
    stamp: str,
    now: datetime,
    account: AccountConfig,
    deliverable: Deliverable,
    backend: str,
    result: Any,
    status: str,
) -> None:
    primary = deliverable.primary
    state.append(
        {
            "stamp": stamp,
            "timestamp": now.isoformat(),
            "account": account.id,
            "kind": deliverable.kind,
            "brief": primary.brief.model_dump(),
            "positive_prompt": primary.positive,
            "negative_prompt": primary.negative,
            "seed": primary.generated.meta.seed,
            "image_model": primary.generated.meta.model_id,
            "device": primary.generated.meta.device,
            "image_sha256": primary.processed.sha256,
            "image_path": str(primary.processed.path),
            "media": [str(m) for m in deliverable.media],
            "caption": deliverable.caption,
            "alt_text": deliverable.alt_text,
            "hashtags": deliverable.hashtags,
            "backend": backend,
            "post_id": getattr(result, "post_id", None),
            "post_url": getattr(result, "url", None),
            "status": status,
        }
    )


# --------------------------------------------------------------------------- #
# Per-account run
# --------------------------------------------------------------------------- #


def _run_account(
    args: argparse.Namespace,
    cfg: Config,
    secrets: Secrets,
    account: AccountConfig,
    accounts_json: dict[str, dict[str, Any]],
    ollama: OllamaClient,
    gen: ImageGenerator,
    llm_model: str,
    now: datetime,
    base_stamp: str,
    run_date: str,
) -> int:
    from .poster import PosterError, build_poster

    # Content profile + theme for this account (sequential, so mutating cfg is safe).
    profile = args.content_profile or account.profile or cfg.content.active_profile
    cfg.content.active_profile = profile
    if profile not in cfg.content.profiles and cfg.content.profiles:
        log.warning("profile %r not defined; using fallback profile", profile)
    if args.description:
        cfg.active_content.theme = args.description
    if account.audio_dir:
        cfg.reel.audio_dir = account.audio_dir

    is_default = account.id == "default"
    out_dir = Path(cfg.state.out_dir) if is_default else Path(cfg.state.out_dir) / account.id
    history_path = cfg.state.history_path if is_default else f"state/history.{account.id}.json"
    state = State(history_path)
    stamp = base_stamp

    seed = (
        args.seed if args.seed is not None else compute_seed(base_stamp + account.id, cfg.seed_salt)
    )
    mix = account.content_mix or cfg.content_mix
    ctype = (
        content_type_by_name(args.content_type)
        if args.content_type
        else select_content_type(mix, random.Random(seed))
    )

    creds = _creds_for(account, accounts_json, secrets)
    backend = account.backend or _infer_backend(creds, account.platform)
    log.info(
        "account=%s profile=%s backend=%s content=%s seed=%d",
        account.id,
        profile,
        backend,
        ctype.name,
        seed,
    )

    ctx = ProductionContext(
        cfg=cfg,
        secrets=secrets,
        ollama=ollama,
        gen=gen,
        state=state,
        seed=seed,
        run_date=run_date,
        stamp=stamp,
        out_dir=out_dir,
        llm_model=llm_model,
        image_only=args.image_only,
        log=log,
    )

    with stage_timer(log, f"produce.{ctype.name}"):
        deliverable = ctype.produce(ctx)

    if args.image_only:
        _write_artifacts(out_dir, stamp, deliverable)
        _record(state, stamp, now, account, deliverable, backend, None, "image-only")
        log.info("image-only complete: %s", deliverable.media[0])
        return ExitCode.OK

    _write_artifacts(out_dir, stamp, deliverable)

    try:
        with stage_timer(log, "post"):
            poster = build_poster(backend, creds, cfg, dry_run=args.dry_run)
            result = poster.publish(
                deliverable.media, deliverable.caption or "", deliverable.alt_text or ""
            )
            if deliverable.comment_text and result.post_id and result.post_id != "dry-run":
                poster.comment(result.post_id, deliverable.comment_text)
            elif deliverable.comment_text and args.dry_run:
                poster.comment("dry-run", deliverable.comment_text)
    except PosterError as exc:
        raise ContentError(ExitCode.POST, f"publish failed: {exc}") from exc
    except Exception as exc:  # noqa: BLE001
        raise ContentError(ExitCode.POST, f"publish failed unexpectedly: {exc}") from exc

    _record(
        state,
        stamp,
        now,
        account,
        deliverable,
        result.backend,
        result,
        "dry-run" if result.dry_run else "posted",
    )
    log.info(
        "account=%s done. backend=%s post_id=%s url=%s dry_run=%s",
        account.id,
        result.backend,
        result.post_id,
        result.url,
        result.dry_run,
    )
    return ExitCode.OK


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #


def run_pipeline(args: argparse.Namespace, cfg: Config, secrets: Secrets) -> int:
    now = datetime.now(UTC)
    run_date = now.strftime("%Y-%m-%d")
    base_stamp = now.strftime("%Y%m%dT%H%M%SZ")

    accounts_json = _load_accounts_json(secrets)
    accounts = _effective_accounts(cfg, secrets, args.account, accounts_json)
    if not accounts:
        log.error("no matching account to run (check --account / config accounts)")
        return ExitCode.CONFIG
    log.info(
        "run stamp=%s accounts=%s dry_run=%s image_only=%s",
        base_stamp,
        [a.id for a in accounts],
        args.dry_run,
        args.image_only,
    )

    llm_model = _llm_model(cfg)
    host = getattr(secrets, "OLLAMA_HOST", "http://127.0.0.1:11434")

    worst = ExitCode.OK
    # Warm the LLM + image model once; reuse across every account and scene.
    with OllamaClient(host, cfg.llm.ready_timeout_s, cfg.llm.request_timeout_s) as ollama:
        try:
            with stage_timer(log, "ollama"):
                ollama.ensure_running()
                ollama.ensure_model(llm_model)
        except Exception as exc:  # noqa: BLE001
            log.error("LLM runtime unavailable: %s", exc)
            return ExitCode.BRIEF

        gen = ImageGenerator(cfg)

        for account in accounts:
            try:
                code = _run_account(
                    args,
                    cfg,
                    secrets,
                    account,
                    accounts_json,
                    ollama,
                    gen,
                    llm_model,
                    now,
                    base_stamp,
                    run_date,
                )
            except ContentError as exc:
                log.error("account %s failed (exit %d): %s", account.id, exc.code, exc)
                code = exc.code
            except SafetyError as exc:
                log.error("account %s blocked by safety gate [%s]: %s", account.id, exc.gate, exc)
                code = ExitCode.SAFETY
            if code != ExitCode.OK:
                worst = code
    return worst


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    setup_logging(args.log_level)
    try:
        cfg = load_config(args.config)
        secrets = load_secrets()
    except Exception as exc:  # noqa: BLE001
        log.error("configuration error: %s", exc)
        return ExitCode.CONFIG

    try:
        return run_pipeline(args, cfg, secrets)
    except KeyboardInterrupt:
        log.error("interrupted")
        return ExitCode.CONFIG


if __name__ == "__main__":
    sys.exit(main())
