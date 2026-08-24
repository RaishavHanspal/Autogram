from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from autogram.safety import (
    SafetyError,
    check_degenerate,
    check_profanity,
    find_profanity,
    run_caption_gates,
)


def test_degenerate_rejects_near_black(cfg):
    img = Image.new("RGB", (256, 256), (0, 0, 0))
    with pytest.raises(SafetyError) as exc:
        check_degenerate(img, cfg)
    assert exc.value.gate == "degenerate"


def test_degenerate_rejects_near_white(cfg):
    img = Image.new("RGB", (256, 256), (255, 255, 255))
    with pytest.raises(SafetyError):
        check_degenerate(img, cfg)


def test_degenerate_rejects_uniform_gray(cfg):
    img = Image.new("RGB", (256, 256), (128, 128, 128))
    with pytest.raises(SafetyError):
        check_degenerate(img, cfg)


def test_degenerate_accepts_gradient(cfg, gradient_image):
    check_degenerate(gradient_image, cfg)  # should not raise


def test_degenerate_accepts_noise(cfg):
    rng = np.random.default_rng(0)
    arr = rng.integers(0, 256, size=(128, 128, 3), dtype="uint8")
    check_degenerate(Image.fromarray(arr), cfg)


def test_profanity_detection():
    words = {"shit", "damn"}
    assert find_profanity("what the shit", words) == ["shit"]
    assert find_profanity("classic", words) == []  # 'ass' not matched as substring


def test_profanity_gate_raises():
    words = {"damn"}
    with pytest.raises(SafetyError) as exc:
        check_profanity("well damn that's nice", words)
    assert exc.value.gate == "profanity"


def test_caption_gate_toggle_off(cfg):
    cfg.gates.profanity = False
    run_caption_gates("damn this", cfg, {"damn"})  # gate off -> no raise
