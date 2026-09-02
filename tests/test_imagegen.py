"""ImageGenerator face-restore guard (no torch/gfpgan needed)."""

from __future__ import annotations

from PIL import Image

from autogram.config import Config
from autogram.imagegen import ImageGenerator


def test_face_restore_disabled_is_noop():
    cfg = Config()
    cfg.image.face_restore = False
    gen = ImageGenerator(cfg)
    img = Image.new("RGB", (32, 32), (100, 120, 140))
    assert gen._restore_faces(img) is img


def test_face_restore_missing_gfpgan_falls_back():
    # gfpgan isn't installed in the test env -> must return the input unchanged
    # and mark itself failed so it doesn't retry on every image.
    cfg = Config()
    cfg.image.face_restore = True
    gen = ImageGenerator(cfg)
    img = Image.new("RGB", (32, 32), (100, 120, 140))
    out = gen._restore_faces(img)
    assert out is img
    assert gen._gfpgan_failed is True
    # A second call is a cheap no-op now.
    assert gen._restore_faces(img) is img
