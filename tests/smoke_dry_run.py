"""Full-pipeline --dry-run smoke test with image gen, LLM, and poster mocked.

Downloads no models and touches no network. Exercises the orchestration wiring
(brief -> image -> gates -> postproc -> caption -> compose -> dry-run publish ->
history) end to end. Exits non-zero on any failure. Used by ci.yml.
"""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path
from unittest import mock

import numpy as np
from PIL import Image

from autogram import run as run_mod
from autogram.imagegen import GeneratedImage, ImageMeta


class _FakeOllama:
    def __init__(self, *a, **k):
        pass

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return None

    def ensure_running(self):
        pass

    def ensure_model(self, model):
        pass

    def chat_json(self, model, messages, seed, temperature):
        # Distinguish brief vs caption by a schema keyword in the system prompt.
        sys_prompt = messages[0]["content"]
        if '"subject"' in sys_prompt:
            return {
                "subject": f"a still life, variation {seed}",
                "setting": "a wooden table",
                "lighting": "soft morning light",
                "mood": "calm",
                "composition": "overhead flat-lay, close-up",
                "color_palette": "warm neutrals",
                "time_of_day": "morning",
                "style_modifiers": ["35mm", "photographic"],
            }
        return {
            "caption": "A quiet morning, distilled.\nLight, wood, and stillness.",
            "hashtags": [
                {"tag": "stilllife", "tier": "broad"},
                {"tag": "minimalism", "tier": "mid"},
                {"tag": "slowliving", "tier": "niche"},
                {"tag": "morninglight", "tier": "mid"},
            ],
            "alt_text": "A still life on a wooden table in soft morning light.",
        }


class _FakeImageGen:
    def __init__(self, cfg):
        self.cfg = cfg

    def generate(self, positive, negative, seed):
        arr = np.tile(np.arange(0, 256, dtype="uint8"), (256, 1))
        img = Image.fromarray(arr).convert("RGB")
        meta = ImageMeta(
            model_id="mock",
            device="cpu",
            dtype="float32",
            steps=1,
            guidance_scale=0.0,
            width=self.cfg.image.width,
            height=self.cfg.image.height,
            seed=seed,
        )
        return GeneratedImage(image=img, meta=meta)


def main() -> int:
    import os

    original_cwd = os.getcwd()
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        (root / "config").mkdir()
        (root / "config" / "config.yaml").write_text(
            "theme: a still life on a wooden table\n"
            "gates:\n  nsfw: false\n  degenerate: true\n  profanity: true\n"
            "image:\n  width: 512\n  height: 512\n",
            encoding="utf-8",
        )
        # profanity/banned files are read from config/ — provide minimal ones.
        (root / "config" / "profanity.txt").write_text("damn\n", encoding="utf-8")
        (root / "config" / "banned_hashtags.txt").write_text(
            "# comment\nspamtag\n", encoding="utf-8"
        )

        os.chdir(root)
        try:
            with (
                mock.patch.object(run_mod, "OllamaClient", _FakeOllama),
                mock.patch.object(run_mod, "ImageGenerator", _FakeImageGen),
            ):
                code = run_mod.main(["--dry-run", "--seed", "4242", "--content-type", "photo"])

            if code != run_mod.ExitCode.OK:
                print(f"SMOKE FAIL: exit code {code}", file=sys.stderr)
                return code
            jpgs = list((root / "out").glob("*.jpg"))
            history = root / "state" / "history.json"
            if not jpgs:
                print("SMOKE FAIL: no JPEG produced", file=sys.stderr)
                return 1
            if not history.exists():
                print("SMOKE FAIL: no history recorded", file=sys.stderr)
                return 1
            print(f"SMOKE OK: {jpgs[0].name}, history written")
            return 0
        finally:
            # Restore cwd so TemporaryDirectory cleanup succeeds on Windows.
            os.chdir(original_cwd)


if __name__ == "__main__":
    sys.exit(main())
