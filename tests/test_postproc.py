from __future__ import annotations

import pytest

from autogram.postproc import ASPECT_DIMS, PostprocError, center_crop_to_aspect, process_image


@pytest.mark.parametrize("aspect,dims", list(ASPECT_DIMS.items()))
def test_process_image_dimensions(cfg, gradient_image, tmp_path, aspect, dims):
    cfg.postproc.aspect = aspect
    out = tmp_path / "img.jpg"
    result = process_image(gradient_image, cfg, out)
    assert (result.width, result.height) == dims
    assert result.path.exists()
    assert result.bytes > 0
    assert len(result.sha256) == 64


def test_center_crop_ratio(gradient_image):
    cropped = center_crop_to_aspect(gradient_image, 1080, 566)
    assert cropped.size == (1080, 566)


def test_process_image_rejects_oversize(cfg, gradient_image, tmp_path):
    cfg.postproc.max_bytes = 10  # impossibly small
    with pytest.raises(PostprocError):
        process_image(gradient_image, cfg, tmp_path / "img.jpg")


def test_process_image_rejects_unsupported_aspect(cfg, gradient_image, tmp_path):
    # Bypass the config validator to exercise the process-time guard.
    object.__setattr__(cfg.postproc, "aspect", "3:2")
    with pytest.raises(PostprocError):
        process_image(gradient_image, cfg, tmp_path / "img.jpg")


def test_output_has_no_exif(cfg, gradient_image, tmp_path):
    from PIL import Image

    out = tmp_path / "img.jpg"
    process_image(gradient_image, cfg, out)
    with Image.open(out) as im:
        assert not im.getexif()
