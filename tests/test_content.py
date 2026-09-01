"""Content-type + multi-account orchestration tests (image gen + LLM mocked)."""

from __future__ import annotations

import json
import random
from pathlib import Path
from unittest import mock

import numpy as np
import pytest
from PIL import Image

from autogram import run as run_mod
from autogram.content.base import REGISTRY, select_content_type
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
        sys_prompt = messages[0]["content"]
        if '"subject"' in sys_prompt:
            return {
                "subject": f"a proposal scene, variation {seed}",
                "setting": "a rooftop at sunset",
                "lighting": "warm golden light",
                "mood": "romantic",
                "composition": "rule of thirds",
                "color_palette": "warm gold",
                "time_of_day": "sunset",
                "style_modifiers": ["50mm", "cinematic"],
            }
        return {
            "caption": "A moment that matters.\nRight here, right now.",
            "hashtags": [{"tag": f"love{i}", "tier": "mid"} for i in range(14)],
            "alt_text": "A couple at sunset on a rooftop.",
        }


class _FakeImageGen:
    """Returns a per-seed-distinct gradient so each scene has a unique hash."""

    def __init__(self, cfg):
        self.cfg = cfg

    def generate(self, positive, negative, seed):
        base = np.tile(np.arange(0, 256, dtype="uint8"), (256, 1))
        arr = ((base.astype(int) + seed) % 256).astype("uint8")
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


def _write_config(root: Path, extra: str = "") -> None:
    (root / "config").mkdir(exist_ok=True)
    (root / "config" / "config.yaml").write_text(
        "theme: a cinematic marriage proposal\n"
        "gates:\n  nsfw: false\n  degenerate: true\n  profanity: true\n"
        "image:\n  width: 256\n  height: 256\n"
        "reel:\n  enabled: true\n  num_scenes: 3\n"
        "carousel:\n  num_slides: 3\n" + extra,
        encoding="utf-8",
    )
    (root / "config" / "profanity.txt").write_text("damn\n", encoding="utf-8")
    (root / "config" / "banned_hashtags.txt").write_text("# c\nspamtag\n", encoding="utf-8")


def _run(root: Path, args: list[str]) -> int:
    import os

    cwd = os.getcwd()
    os.chdir(root)
    try:
        with (
            mock.patch.object(run_mod, "OllamaClient", _FakeOllama),
            mock.patch.object(run_mod, "ImageGenerator", _FakeImageGen),
        ):
            return run_mod.main(args)
    finally:
        os.chdir(cwd)


# --------------------------------------------------------------------------- #
# Registry / selection
# --------------------------------------------------------------------------- #


def test_registry_has_all_three_types():
    assert set(REGISTRY) == {"photo", "reel", "carousel"}


def test_select_content_type_is_seed_deterministic():
    mix = {"photo": 1, "reel": 2, "carousel": 1}
    a = select_content_type(mix, random.Random(123)).name
    b = select_content_type(mix, random.Random(123)).name
    assert a == b


def test_select_content_type_respects_zero_weight():
    mix = {"photo": 0, "reel": 0, "carousel": 5}
    picks = {select_content_type(mix, random.Random(i)).name for i in range(20)}
    assert picks == {"carousel"}


# --------------------------------------------------------------------------- #
# Content types end to end (dry-run)
# --------------------------------------------------------------------------- #


def test_photo_produces_single_image(tmp_path):
    _write_config(tmp_path)
    code = _run(tmp_path, ["--dry-run", "--seed", "5", "--content-type", "photo"])
    assert code == run_mod.ExitCode.OK
    jpgs = sorted((tmp_path / "out").glob("*.jpg"))
    assert len(jpgs) == 1
    assert (tmp_path / "state" / "history.json").exists()


def test_carousel_produces_multiple_images(tmp_path):
    _write_config(tmp_path)
    code = _run(tmp_path, ["--dry-run", "--seed", "5", "--content-type", "carousel"])
    assert code == run_mod.ExitCode.OK
    jpgs = sorted((tmp_path / "out").glob("*.jpg"))
    assert len(jpgs) == 3  # carousel.num_slides


def test_reel_runs_and_records(tmp_path):
    # ffmpeg may be absent (e.g. the CI test job): the reel then falls back to a
    # still image. Either way the run must succeed and record history.
    _write_config(tmp_path)
    code = _run(tmp_path, ["--dry-run", "--seed", "5", "--content-type", "reel"])
    assert code == run_mod.ExitCode.OK
    assert (tmp_path / "state" / "history.json").exists()
    assert sorted((tmp_path / "out").glob("*.jpg"))  # scene stills exist


# --------------------------------------------------------------------------- #
# Multi-account
# --------------------------------------------------------------------------- #


def test_multi_account_runs_each_with_isolated_state(tmp_path):
    _write_config(
        tmp_path,
        extra=(
            "accounts:\n"
            "  - id: alpha\n    content_mix: {photo: 1}\n"
            "  - id: beta\n    content_mix: {photo: 1}\n"
        ),
    )
    code = _run(tmp_path, ["--dry-run", "--seed", "9"])
    assert code == run_mod.ExitCode.OK
    assert (tmp_path / "out" / "alpha").is_dir()
    assert (tmp_path / "out" / "beta").is_dir()
    assert (tmp_path / "state" / "history.alpha.json").exists()
    assert (tmp_path / "state" / "history.beta.json").exists()


def test_single_account_filter(tmp_path):
    _write_config(
        tmp_path,
        extra=(
            "accounts:\n"
            "  - id: alpha\n    content_mix: {photo: 1}\n"
            "  - id: beta\n    content_mix: {photo: 1}\n"
        ),
    )
    code = _run(tmp_path, ["--dry-run", "--seed", "9", "--account", "beta"])
    assert code == run_mod.ExitCode.OK
    assert (tmp_path / "out" / "beta").is_dir()
    assert not (tmp_path / "out" / "alpha").exists()


@pytest.mark.parametrize("ctype", ["photo", "carousel", "reel"])
def test_image_only_skips_publish(tmp_path, ctype):
    _write_config(tmp_path)
    code = _run(tmp_path, ["--image-only", "--seed", "3", "--content-type", ctype])
    assert code == run_mod.ExitCode.OK
    # image-only writes no caption .txt
    assert not sorted((tmp_path / "out").glob("*.txt"))


# --------------------------------------------------------------------------- #
# Secret-only accounts + backend inference
# --------------------------------------------------------------------------- #


def test_infer_backend_from_creds():
    graph = {"ig_access_token": "t", "ig_user_id": "1"}
    insta = {"ig_username": "u", "ig_password": "p"}
    yt = {"youtube_refresh_token": "r"}
    assert run_mod._infer_backend(graph, "instagram") == "graph"
    assert run_mod._infer_backend(insta, "instagram") == "instagrapi"
    assert run_mod._infer_backend(yt, "instagram") == "youtube"
    assert run_mod._infer_backend({}, "youtube") == "youtube"
    assert run_mod._infer_backend({}, "instagram") == "instagrapi"


def test_secret_only_accounts_are_synthesized(tmp_path, monkeypatch):
    # No accounts declared in YAML — AUTOGRAM_ACCOUNTS alone must configure them,
    # each routed to the right backend by its credentials (graph vs instagrapi).
    _write_config(tmp_path)
    monkeypatch.setenv(
        "AUTOGRAM_ACCOUNTS",
        json.dumps(
            [
                {"name": "A", "id": "acct_a", "ig_access_token": "tok", "ig_user_id": "123"},
                {"name": "B", "id": "acct_b", "ig_username": "u", "ig_password": "p"},
            ]
        ),
    )
    code = _run(tmp_path, ["--dry-run", "--seed", "4", "--content-type", "photo"])
    assert code == run_mod.ExitCode.OK
    assert (tmp_path / "out" / "acct_a").is_dir()
    assert (tmp_path / "out" / "acct_b").is_dir()

    hist_a = json.loads((tmp_path / "state" / "history.acct_a.json").read_text())
    hist_b = json.loads((tmp_path / "state" / "history.acct_b.json").read_text())
    # Backend routed from the creds present: graph (access token) vs instagrapi.
    assert hist_a[-1]["backend"] == "graph"
    assert hist_b[-1]["backend"] == "instagrapi"
