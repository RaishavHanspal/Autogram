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
    from .scene import Brief

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
        num_ctx: int = 4096,
        num_predict: int = 600,
    ) -> None:
        self.host = host.rstrip("/")
        self.ready_timeout_s = ready_timeout_s
        self.request_timeout_s = request_timeout_s
        self.num_ctx = num_ctx
        self.num_predict = num_predict
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
        # Ollama silently truncates the START of a prompt that overflows num_ctx
        # (losing the system prompt and schema), so flag it loudly instead.
        est_tokens = estimate_tokens(messages)
        if est_tokens + self.num_predict > self.num_ctx:
            log.warning(
                "prompt ~%d tokens + %d output exceeds num_ctx %d; the start will be truncated",
                est_tokens,
                self.num_predict,
                self.num_ctx,
            )
        else:
            log.debug("prompt ~%d tokens", est_tokens)
        payload = {
            "model": model,
            "messages": messages,
            "stream": False,
            "format": "json",
            "options": {
                "temperature": temperature,
                "seed": seed,
                "num_ctx": self.num_ctx,
                "num_predict": self.num_predict,
            },
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


def estimate_tokens(messages: list[dict[str, str]]) -> int:
    """Rough token count (~4 chars/token for English) — cheap, no tokenizer."""
    return sum(len(m.get("content", "")) for m in messages) // 4 + 8 * len(messages)


def clip_words(text: str, max_words: int) -> str:
    """Collapse whitespace and keep at most ``max_words`` words (prompt budget)."""
    words = text.split()
    return " ".join(words[:max_words])


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
# Instagram limit for feed posts + Reels since Dec 2025 (caption + comments).
IG_HASHTAG_HARD_CAP = 5


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
    """Normalize, dedupe, filter banned, keep brand tags, enforce counts/cap.

    Brand tags get reserved slots so the topical tags are trimmed first — with
    only 5 tags allowed, appending brands and then truncating would drop them.
    """
    limit = min(cfg.hashtags.max_count, IG_HASHTAG_HARD_CAP)
    seen: set[str] = set()

    def _collect(tags: list[str]) -> list[str]:
        out: list[str] = []
        for tag in tags:
            norm = normalize_tag(tag)
            if not norm:
                continue
            key = norm.lstrip("#").lower()
            if key in seen or key in banned:
                continue
            seen.add(key)
            out.append(norm)
        return out

    brands = _collect(brand_tags_for(cfg))[:limit]
    topical = _collect([rt.tag for rt in raw_tags])[: limit - len(brands)]
    return topical + brands


def brand_tags_for(cfg: Config) -> list[str]:
    """Profile brand tags when set, else the global hashtags.brand_tags."""
    profile_tags = cfg.active_content.brand_tags
    return list(profile_tags) if profile_tags is not None else list(cfg.hashtags.brand_tags)


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
    "[\U0001f300-\U0001faff\U00002600-\U000027bf\U0001f1e6-\U0001f1ff]",
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
            f"caption+hashtags is {len(body)} chars, exceeds limit {cfg.caption.max_length}"
        )
    return body


# --------------------------------------------------------------------------- #
# Generation
# --------------------------------------------------------------------------- #
# Brief fields worth showing the copywriter; everything else (prompts, seeds,
# framing jargon) only burns tokens and drags the caption toward describing
# the image instead of the moment.
_CAPTION_FIELDS: tuple[str, ...] = (
    "subject",
    "setting",
    "location_name",
    "mood",
    "lighting",
    "time_of_day",
    "headline",
    "points",
)


def brief_digest(brief: Brief, max_words: int = 30) -> str:
    """Compact ``key: value`` lines of the non-empty, caption-relevant fields."""
    data = brief.model_dump()
    lines: list[str] = []
    seen: set[str] = set()
    for key in _CAPTION_FIELDS:
        value = data.get(key)
        if isinstance(value, list):
            value = " | ".join(str(v) for v in value if v)
        text = clip_words(str(value or ""), max_words)
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        lines.append(f"{key}: {text}")
    if brief.proposal_direction:
        if brief.proposal_direction == "boy_proposes_to_girl":
            story = "he proposes to her"
        else:
            story = "she proposes to him"
        if brief.third_person_present:
            story += "; a heartbroken woman watches from afar"
        lines.append(f"story: {story}")
    return "\n".join(lines)


def _build_messages(brief: Brief, cfg: Config, error_feedback: str | None) -> list[dict[str, str]]:
    schema = (
        '{"caption": "string", "hashtags": '
        '[{"tag": "string", "tier": "broad|niche"}], "alt_text": "string"}'
    )
    voice = clip_words(cfg.active_content.caption_voice or cfg.caption.tone, 40)
    system = (
        "You write Instagram captions people stop for, save and share. "
        f"Voice: {voice} "
        f"Respond ONLY with one JSON object matching: {schema}. No prose, no code fences."
    )
    limit = min(cfg.hashtags.max_count, IG_HASHTAG_HARD_CAP)
    n_topical = max(1, limit - len(brand_tags_for(cfg)))
    user = (
        f"Post:\n{brief_digest(brief)}\n\n"
        "Caption structure (blank line between parts):\n"
        f"1. Hook: ONE line under {cfg.caption.hook_max_chars} characters, specific, "
        "sparks curiosity or emotion. Never open with 'This', 'Here' or a hashtag.\n"
        "2. Body: 2-4 short lines. Name the subject and place in plain searchable words "
        "(Instagram search reads captions). One sensory detail or one real insight.\n"
        "3. Close: one natural call to action: a question, or an invite to save/share.\n"
        "Rules: no cliches (wanderlust, goals, vibes, magic), no @mentions, "
        f"at most {cfg.caption.emoji_budget} emoji, no hashtags inside the caption.\n"
        f"hashtags: exactly {n_topical} specific tags, no '#', no spaces; "
        "1 'broad', the rest 'niche'.\n"
        "alt_text: one plain factual sentence describing the image."
    )
    if error_feedback:
        user += f"\nYour previous reply was invalid: {error_feedback}\nReply with valid JSON only."
    return [
        {"role": "system", "content": system},
        {"role": "user", "content": user},
    ]


def _fallback_caption(brief: Brief, cfg: Config, banned: set[str]) -> CaptionResult:
    """Deterministic template so a run never dies on LLM formatting."""
    log.warning("using deterministic fallback caption")
    # Profile-neutral on purpose: the old romance template ("Just us, just
    # this") leaked onto travel and AI posts whenever the LLM failed.
    hook = (brief.headline or brief.subject).strip().rstrip(".")
    parts = [f"{hook[:1].upper()}{hook[1:]}."]
    if brief.points:
        parts.append("\n".join(f"- {p}" for p in brief.points))
    elif brief.setting:
        parts.append(f"{brief.setting[:1].upper()}{brief.setting[1:]}.")
    parts.append("Save this for later.")
    body = "\n\n".join(parts)
    stop = {"with", "from", "through", "into", "over", "under", "their", "this", "that"}
    raw = [
        _RawHashtag(tag=w, tier="niche")
        for w in re.findall(r"[A-Za-z0-9]+", f"{brief.subject} {brief.setting}")
        if len(w) > 3 and w.lower() not in stop
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
