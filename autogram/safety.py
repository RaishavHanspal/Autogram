"""Safety and quality gates. Any failing gate aborts the run (nothing posted).

Gates (each individually toggleable in config):
  * NSFW      — CompVis/stable-diffusion-safety-checker (see justification below)
  * degenerate — reject near-uniform / near-black / near-white output, a real
                 failure mode of turbo models at very low step counts
  * profanity  — local wordlist, word-boundary, case-insensitive

NSFW model choice: we use the official CompVis safety checker that ships as a
class inside `diffusers`. It is the canonical, well-understood NSFW gate, needs
no bespoke thresholds, and its weights (~1.2 GB) cache in HF_HOME next to the
diffusion model. On CPU it scores a single 512px image in ~1-2 s, which is
negligible against generation time — so the heavier-but-correct checker wins
over a hand-rolled CLIP classifier here.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from .config import Config
from .logging_utils import get_logger

if TYPE_CHECKING:
    from PIL.Image import Image

log = get_logger("safety")


class SafetyError(RuntimeError):
    """Raised when a gate fails. `gate` identifies which one."""

    def __init__(self, gate: str, message: str) -> None:
        super().__init__(message)
        self.gate = gate


# --------------------------------------------------------------------------- #
# Degenerate-image gate
# --------------------------------------------------------------------------- #
def image_stats(image: Image) -> tuple[float, float]:
    """Return (mean, variance) of the grayscale image in 0-255."""
    import numpy as np

    gray = image.convert("L")
    arr = np.asarray(gray, dtype="float64")
    return float(arr.mean()), float(arr.var())


def check_degenerate(image: Image, cfg: Config) -> None:
    mean, variance = image_stats(image)
    log.info("degenerate check: mean=%.1f variance=%.1f", mean, variance)
    if variance < cfg.gates.degenerate_min_variance:
        raise SafetyError(
            "degenerate",
            f"image is near-uniform (variance {variance:.1f} < "
            f"{cfg.gates.degenerate_min_variance})",
        )
    if mean < cfg.gates.degenerate_dark_mean:
        raise SafetyError(
            "degenerate",
            f"image is near-black (mean {mean:.1f} < {cfg.gates.degenerate_dark_mean})",
        )
    if mean > cfg.gates.degenerate_bright_mean:
        raise SafetyError(
            "degenerate",
            f"image is near-white (mean {mean:.1f} > {cfg.gates.degenerate_bright_mean})",
        )


# --------------------------------------------------------------------------- #
# NSFW gate
# --------------------------------------------------------------------------- #
_safety_checker: Any = None
_feature_extractor: Any = None


def _load_nsfw_model() -> tuple[Any, Any]:
    global _safety_checker, _feature_extractor
    if _safety_checker is not None:
        return _safety_checker, _feature_extractor
    from diffusers.pipelines.stable_diffusion.safety_checker import (
        StableDiffusionSafetyChecker,
    )
    from transformers import CLIPImageProcessor

    model_id = "CompVis/stable-diffusion-safety-checker"
    _safety_checker = StableDiffusionSafetyChecker.from_pretrained(model_id)
    _feature_extractor = CLIPImageProcessor.from_pretrained(model_id)
    return _safety_checker, _feature_extractor


def check_nsfw(image: Image) -> None:
    import numpy as np

    checker, extractor = _load_nsfw_model()
    rgb = image.convert("RGB")
    clip_input = extractor(images=rgb, return_tensors="pt").pixel_values
    arr = np.expand_dims(np.asarray(rgb), axis=0)
    _, has_nsfw = checker(images=arr, clip_input=clip_input)
    if any(bool(x) for x in has_nsfw):
        raise SafetyError("nsfw", "NSFW content detected by safety checker")
    log.info("nsfw check passed")


# --------------------------------------------------------------------------- #
# Profanity gate
# --------------------------------------------------------------------------- #
def load_profanity(path: str = "config/profanity.txt") -> set[str]:
    words: set[str] = set()
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                s = line.strip()
                if s and not s.startswith("#"):
                    words.add(s.lower())
    except FileNotFoundError:
        log.warning("profanity file not found: %s", path)
    return words


def find_profanity(text: str, words: set[str]) -> list[str]:
    if not words:
        return []
    lowered = text.lower()
    hits: list[str] = []
    for w in words:
        if re.search(rf"\b{re.escape(w)}\b", lowered):
            hits.append(w)
    return hits


def check_profanity(text: str, words: set[str] | None = None) -> None:
    if words is None:
        words = load_profanity()
    hits = find_profanity(text, words)
    if hits:
        raise SafetyError("profanity", f"caption contains banned terms: {sorted(hits)}")
    log.info("profanity check passed")


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #
def run_image_gates(image: Image, cfg: Config) -> None:
    """Run enabled image gates. Raises SafetyError on the first failure."""
    if cfg.gates.degenerate:
        check_degenerate(image, cfg)
    if cfg.gates.nsfw:
        check_nsfw(image)


def run_caption_gates(caption: str, cfg: Config, words: set[str] | None = None) -> None:
    if cfg.gates.profanity:
        check_profanity(caption, words)
