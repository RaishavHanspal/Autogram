"""Image generation: brief prompts -> PNG via diffusers.

CPU is the default and only guaranteed path (GitHub runners have no GPU):
fp32, attention slicing, all cores. When CUDA is present (a dev machine or a
self-hosted GPU runner) the SAME code path auto-upgrades to fp16 and the
configured hq_model (default FLUX.1-schnell) for real quality.

torch/diffusers are imported lazily so unit tests and `--help` don't pay the
import cost and don't require the heavy deps installed.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from .config import Config
from .logging_utils import get_logger

if TYPE_CHECKING:
    from PIL.Image import Image

log = get_logger("imagegen")


@dataclass
class ImageMeta:
    model_id: str
    device: str
    dtype: str
    steps: int
    guidance_scale: float
    width: int
    height: int
    seed: int


@dataclass
class GeneratedImage:
    image: Image
    meta: ImageMeta


def _resolve_device(cfg: Config) -> tuple[str, str, Any, str]:
    """Return (device, dtype_name, torch_dtype, model_id)."""
    import torch

    if torch.cuda.is_available():
        log.info("CUDA detected -> fp16 + hq model")
        return "cuda", "float16", torch.float16, cfg.image.hq_model
    log.info("no CUDA -> CPU fp32 + default model")
    return "cpu", "float32", torch.float32, cfg.image.model


class ImageGenerator:
    """Loads a diffusion pipeline (cached in HF_HOME) and renders images."""

    def __init__(self, cfg: Config) -> None:
        self.cfg = cfg
        self._pipe: Any = None
        self._device: str = "cpu"
        self._dtype_name: str = "float32"
        self._model_id: str = cfg.image.model

    def _load(self) -> None:
        if self._pipe is not None:
            return
        import torch
        from diffusers import AutoPipelineForText2Image

        device, dtype_name, torch_dtype, model_id = _resolve_device(self.cfg)
        self._device, self._dtype_name, self._model_id = device, dtype_name, model_id

        # Ensure the cache lands where Actions can cache it.
        os.environ.setdefault("HF_HOME", os.path.expanduser("~/.cache/huggingface"))
        log.info("loading pipeline %s (HF_HOME=%s)", model_id, os.environ["HF_HOME"])

        pipe = AutoPipelineForText2Image.from_pretrained(
            model_id, torch_dtype=torch_dtype, safety_checker=None
        )
        pipe = pipe.to(device)

        if device == "cpu":
            pipe.enable_attention_slicing()
            torch.set_num_threads(os.cpu_count() or 4)
        # Silence the tokenizer parallelism warning under subprocess spawns.
        os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
        self._pipe = pipe

    def generate(self, positive: str, negative: str, seed: int) -> GeneratedImage:
        self._load()
        import torch

        generator = torch.Generator(device=self._device).manual_seed(seed)
        # Distilled models (FLUX schnell, *-turbo, LCM) need very few steps and
        # zero guidance; a normal photoreal SD checkpoint needs real CFG + steps.
        model_lc = self._model_id.lower()
        is_distilled = any(k in model_lc for k in ("flux", "turbo", "schnell", "lcm"))
        if self._device == "cuda" or is_distilled:
            steps = self.cfg.image.hq_steps
            guidance = self.cfg.image.hq_guidance_scale
        else:
            steps = self.cfg.image.steps
            guidance = self.cfg.image.guidance_scale

        kwargs: dict[str, Any] = {
            "prompt": positive,
            "num_inference_steps": steps,
            "guidance_scale": guidance,
            "width": self.cfg.image.width,
            "height": self.cfg.image.height,
            "generator": generator,
        }
        # FLUX schnell does not accept a negative prompt; SD/SDXL do.
        if "flux" not in model_lc:
            kwargs["negative_prompt"] = negative

        log.info(
            "generating %dx%d, %d steps, guidance %.1f, seed %d (model=%s)",
            self.cfg.image.width,
            self.cfg.image.height,
            steps,
            guidance,
            seed,
            self._model_id,
        )
        result = self._pipe(**kwargs)
        image = result.images[0]
        meta = ImageMeta(
            model_id=self._model_id,
            device=self._device,
            dtype=self._dtype_name,
            steps=steps,
            guidance_scale=guidance,
            width=self.cfg.image.width,
            height=self.cfg.image.height,
            seed=seed,
        )
        return GeneratedImage(image=image, meta=meta)