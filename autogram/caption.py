"""Caption + hashtags + alt text via a self-hosted Ollama LLM.

This module also owns the Ollama runtime lifecycle (OllamaClient), which
brief.py reuses. The client never assumes a running daemon: it detects one,
and if absent installs Ollama (Linux) and spawns `ollama serve`, health-polls
until ready, and tears it down cleanly on exit.
"""

from __future__ import annotations

import atexit
import json
import platform
import re
import shutil
import subprocess
import time
from typing import TYPE_CHECKING, Any

import requests
from pydantic import BaseModel, Field, ValidationError

from .config import Config
from .logging_utils import get_logger

if TYPE_CHECKING:
    from .brief import Brief

log = get_logger("caption")


# --------------------------------------------------------------------------- #
# Ollama runtime
# --------------------------------------------------------------------------- #
class OllamaError(RuntimeError):
    pass


class OllamaClient:
    """Manages the Ollama daemon lifecycle and issues chat requests."""

    def __init__(
        self,
        host: str,
        ready_timeout_s: int = 120,
        request_timeout_s: int = 180,
    ) -> None:
        self.host = host.rstrip("/")
        self.ready_timeout_s = ready_timeout_s
        self.request_timeout_s = request_timeout_s
        self._proc: subprocess.Popen[bytes] | None = None
        self._started_by_us = False

    # -- lifecycle --------------------------------------------------------- #
    def is_up(self) -> bool:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=3)
            return r.status_code == 200
        except requests.RequestException:
            return False

    def ensure_running(self) -> None:
        if self.is_up():
            log.info("ollama daemon already running at %s", self.host)
            return
        self._install_if_missing()
        self._spawn_serve()
        self._wait_ready()
        atexit.register(self.close)

    def _install_if_missing(self) -> None:
        if shutil.which("ollama"):
            return
        if platform.system() != "Linux":
            raise OllamaError(
                "ollama binary not found and auto-install is Linux-only. "
                "Install Ollama from https://ollama.com/download and retry."
            )
        log.info("installing ollama (linux official script)")
        subprocess.run(
            "curl -fsSL https://ollama.com/install.sh | sh",
            shell=True,
            check=True,
        )
        if not shutil.which("ollama"):
            raise OllamaError("ollama install script completed but binary still not on PATH")

    def _spawn_serve(self) -> None:
        log.info("spawning `ollama serve`")
        env = _ollama_env(self.host)
        self._proc = subprocess.Popen(
            ["ollama", "serve"],
            env=env,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        self._started_by_us = True

    def _wait_ready(self) -> None:
        deadline = time.monotonic() + self.ready_timeout_s
        delay = 0.5
        while time.monotonic() < deadline:
            if self.is_up():
                log.info("ollama daemon ready")
                return
            if self._proc and self._proc.poll() is not None:
                raise OllamaError(f"`ollama serve` exited early (code {self._proc.returncode})")
            time.sleep(delay)
            delay = min(delay * 1.5, 5.0)
        raise OllamaError(f"ollama not ready within {self.ready_timeout_s}s")

    def ensure_model(self, model: str) -> None:
        try:
            r = requests.get(f"{self.host}/api/tags", timeout=10)
            r.raise_for_status()
            names = {m.get("name", "") for m in r.json().get("models", [])}
        except requests.RequestException as exc:
            raise OllamaError(f"cannot list ollama models: {exc}") from exc
        if model in names or any(n.split(":")[0] == model for n in names):
            log.info("model %s already present", model)
            return
        log.info("pulling model %s (first run; cached afterwards)", model)
        subprocess.run(
            ["ollama", "pull", model],
            env=_ollama_env(self.host),
            check=True,
        )

    def close(self) -> None:
        if self._proc and self._started_by_us and self._proc.poll() is None:
            log.info("stopping ollama daemon we started")
            self._proc.terminate()
            try:
                self._proc.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self._proc.kill()
        self._proc = None

    def __enter__(self) -> OllamaClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- chat -------------------------------------------------------------- #
    def chat_json(
        self,
        model: str,
        messages: list[dict[str, str]],
        seed: int,
        temperature: float,
    ) -> dict[str, Any]:
        """POST /api/chat with JSON format; return parsed JSON object."""
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {"temperature": temperature, "seed": seed},
        }
        try:
            r = requests.post(
                f"{self.host}/api/chat",
                json=payload,
                timeout=self.request_timeout_s,
            )
            r.raise_for_status()
        except requests.RequestException as exc:
            raise OllamaError(f"ollama chat request failed: {exc}") from exc
        content = r.json().get("message", {}).get("content", "")
        try:
            return json.loads(content)
        except json.JSONDecodeError as exc:
            raise OllamaError(f"ollama returned non-JSON content: {content[:200]!r}") from exc


def _ollama_env(host: str) -> dict[str, str]:
    import os

    env = dict(os.environ)
    # ollama serve honours OLLAMA_HOST as host:port (no scheme).
    hostport = host.replace("http://", "").replace("https://", "")
    env["OLLAMA_HOST"] = hostport
    return env


# --------------------------------------------------------------------------- #
# Caption model
# --------------------------------------------------------------------------- #
class CaptionResult(BaseModel):
    caption: str
    hashtags: list[str] = Field(default_factory=list)
    alt_text: str = ""


class _RawHashtag(BaseModel):
    tag: str
    tier: str = "mid"  # broad | mid | niche


class _LlmCaption(BaseModel):
    caption: str
    hashtags: list[_RawHashtag] = Field(default_factory=list)
    alt_text: str


# --------------------------------------------------------------------------- #
# Hashtag normalization / filtering / tiering
# --------------------------------------------------------------------------- #
_TAG_RE = re.compile(r"^#[A-Za-z0-9_]{2,29}$")
IG_HASHTAG_HARD_CAP = 30


def load_banned_hashtags(path: str = "config/banned_hashtags.txt") -> set[str]:
    banned: set[str] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if not s:
                    continue
                # A '#'-prefixed line with a space is a comment; "#tag" is a tag.
                if s.startswith("#") and " " in s:
                    continue
                banned.add(s.lstrip("#").lower())
    except FileNotFoundError:
        log.warning("banned hashtag file not found: %s", path)
    return banned


def normalize_tag(raw: str) -> str | None:
    """Return a validated '#tag' or None if invalid.

    Only leading/trailing whitespace is stripped. A tag with internal
    whitespace (a phrase, not a hashtag) fails the regex and is dropped, per
    spec — we do NOT silently merge words together.
    """
    core = raw.strip().lstrip("#").strip()
    if not core:
        return None
    candidate = f"#{core}"
    return candidate if _TAG_RE.match(candidate) else None


def process_hashtags(
    raw_tags: list[_RawHashtag],
    cfg: Config,
    banned: set[str],
) -> list[str]:
    """Normalize, dedupe, filter banned, append brand tags, enforce counts/cap."""
    seen: set[str] = set()
    kept: list[str] = []

    def _add(tag: str) -> None:
        norm = normalize_tag(tag)
        if not norm:
            return
        key = norm.lstrip("#").lower()
        if key in seen or key in banned:
            return
        seen.add(key)
        kept.append(norm)

    for rt in raw_tags:
        _add(rt.tag)

    # Always append configured brand tags (also normalized/deduped).
    for brand in cfg.hashtags.brand_tags:
        _add(brand)

    # Enforce max_count first (leave room mentally for the hard cap), then cap.
    if len(kept) > cfg.hashtags.max_count:
        kept = kept[: cfg.hashtags.max_count]
    if len(kept) > IG_HASHTAG_HARD_CAP:
        kept = kept[:IG_HASHTAG_HARD_CAP]
    return kept


def validate_tier_distribution(
    raw_tags: list[_RawHashtag], cfg: Config, tolerance: float = 0.25
) -> bool:
    """Check the broad/mid/niche mix is roughly on target. Best-effort."""
    if not raw_tags:
        return False
    counts = {"broad": 0, "mid": 0, "niche": 0}
    for rt in raw_tags:
        counts[rt.tier if rt.tier in counts else "mid"] += 1
    total = sum(counts.values())
    frac = {k: v / total for k, v in counts.items()}
    targets = {
        "broad": cfg.hashtags.tier_broad,
        "mid": cfg.hashtags.tier_mid,
        "niche": cfg.hashtags.tier_niche,
    }
    return all(abs(frac[k] - targets[k]) <= tolerance for k in targets)


# --------------------------------------------------------------------------- #
# Caption post-processing (rules enforced in code, not only the prompt)
# --------------------------------------------------------------------------- #
_EMOJI_RE = re.compile(
    "[" "\U0001f300-\U0001faff" "\U00002600-\U000027bf" "\U0001f1e6-\U0001f1ff" "]",
    flags=re.UNICODE,
)
_MENTION_RE = re.compile(r"(?<!\w)@\w+")


def enforce_caption_rules(caption: str, cfg: Config) -> str:
    """Trim emoji to budget, strip invented @mentions, collapse blank lines."""
    # Strip invented @mentions (we never mention accounts we can't verify).
    caption = _MENTION_RE.sub("", caption)

    # Enforce emoji budget.
    if cfg.caption.emoji_budget >= 0:
        seen = 0

        def _keep(m: re.Match[str]) -> str:
            nonlocal seen
            seen += 1
            return m.group(0) if seen <= cfg.caption.emoji_budget else ""

        caption = _EMOJI_RE.sub(_keep, caption)

    # Collapse excessive whitespace but keep paragraph breaks.
    caption = re.sub(r"[ \t]+\n", "\n", caption).strip()
    caption = re.sub(r"\n{3,}", "\n\n", caption)
    return caption


def compose_final_caption(caption: str, hashtags: list[str], cfg: Config) -> str:
    """Combine caption + hashtag block per placement, enforcing max_length."""
    body = caption
    if cfg.caption.hashtag_placement == "caption" and hashtags:
        body = f"{caption}\n\n{' '.join(hashtags)}"
    if len(body) > cfg.caption.max_length:
        raise ValueError(
            f"caption+hashtags is {len(body)} chars, exceeds limit " f"{cfg.caption.max_length}"
        )
    return body


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
def _build_messages(brief: Brief, cfg: Config, error_feedback: str | None) -> list[dict[str, str]]:
    schema = (
        '{"caption": "string", "hashtags": '
        '[{"tag": "string", "tier": "broad|mid|niche"}], "alt_text": "string"}'
    )
    system = (
        "You are an expert Instagram copywriter. Respond ONLY with a single JSON "
        f"object matching this schema exactly: {schema}. No prose, no code fences."
    )
    n = cfg.hashtags.max_count
    user = (
        f"Write an Instagram post for this creative brief:\n"
        f"{brief.model_dump_json(indent=2)}\n\n"
        f"Requirements:\n"
        f"- Tone/voice: {cfg.caption.tone}.\n"
        f"- The FIRST line must work as a standalone hook.\n"
        f"- At most {cfg.caption.emoji_budget} emoji total.\n"
        f"- Do NOT invent @mentions of accounts.\n"
        f"- Keep the whole caption well under {cfg.caption.max_length} characters.\n"
        f"- Provide {cfg.hashtags.min_count}-{n} hashtags, each labelled with a tier: "
        f"~30% 'broad' (>1M posts), ~50% 'mid', ~20% 'niche'.\n"
        f"- alt_text: one factual sentence describing the image for accessibility.\n"
    )
    if error_feedback:
        user += f"\nYour previous reply was invalid: {error_feedback}\nFix it and reply with valid JSON only."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _fallback_caption(brief: Brief, cfg: Config, banned: set[str]) -> CaptionResult:
    """Deterministic template so a run never dies on LLM formatting."""
    log.warning("using deterministic fallback caption")
    hook = f"{brief.subject.capitalize()} in {brief.lighting}."
    body = (
        f"{hook}\n\n{brief.mood.capitalize()}, {brief.composition}. "
        f"A study in {brief.color_palette}."
    )
    raw = [
        _RawHashtag(tag=w, tier="mid")
        for w in re.findall(
            r"[A-Za-z0-9]+", f"{brief.subject} {brief.mood} {brief.style_modifiers}"
        )
    ]
    tags = process_hashtags(raw, cfg, banned)
    caption = enforce_caption_rules(body, cfg)
    return CaptionResult(
        caption=caption,
        hashtags=tags,
        alt_text=f"{brief.subject}, {brief.setting}, {brief.lighting}.",
    )


def generate_caption(
    client: OllamaClient,
    brief: Brief,
    cfg: Config,
    seed: int,
    model: str,
    banned: set[str] | None = None,
) -> CaptionResult:
    """Generate caption+hashtags+alt text, validating and retrying, with fallback."""
    if banned is None:
        banned = load_banned_hashtags()

    error_feedback: str | None = None
    for attempt in range(1, cfg.llm.max_retries + 1):
        try:
            raw = client.chat_json(
                model=model,
                messages=_build_messages(brief, cfg, error_feedback),
                seed=seed,
                temperature=cfg.llm.temperature,
            )
            parsed = _LlmCaption.model_validate(raw)
        except (OllamaError, ValidationError) as exc:
            error_feedback = str(exc)[:300]
            log.warning(
                "caption attempt %d/%d failed: %s", attempt, cfg.llm.max_retries, error_feedback
            )
            continue

        caption = enforce_caption_rules(parsed.caption, cfg)
        hashtags = process_hashtags(parsed.hashtags, cfg, banned)
        if len(hashtags) < cfg.hashtags.min_count:
            error_feedback = (
                f"only {len(hashtags)} valid hashtags survived filtering; "
                f"need at least {cfg.hashtags.min_count}"
            )
            log.warning("caption attempt %d: %s", attempt, error_feedback)
            continue

        # Validate combined length up-front (placement-aware).
        try:
            compose_final_caption(caption, hashtags, cfg)
        except ValueError as exc:
            error_feedback = str(exc)
            log.warning("caption attempt %d: %s", attempt, error_feedback)
            continue

        return CaptionResult(caption=caption, hashtags=hashtags, alt_text=parsed.alt_text.strip())

    return _fallback_caption(brief, cfg, banned)
