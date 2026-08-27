"""Image post-processing: raw PNG/PIL image -> Instagram-ready JPEG.

Resize + center-crop to the configured aspect, convert to sRGB, mild unsharp
mask, JPEG quality 92, strip all EXIF. Hard-fails if the result exceeds 8 MB or
falls outside Instagram's 0.8-1.91 aspect window.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageFilter

from .config import Config
from .logging_utils import get_logger

log = get_logger("postproc")

# Target pixel dimensions per supported aspect.
ASPECT_DIMS: dict[str, tuple[int, int]] = {
    "1:1": (1080, 1080),
    "4:5": (1080, 1350),
    "1.91:1": (1080, 566),
}

IG_MIN_ASPECT = 0.8
IG_MAX_ASPECT = 1.91


class PostprocError(RuntimeError):
    pass


@dataclass
class ProcessedImage:
    path: Path
    width: int
    height: int
    bytes: int
    sha256: str


def center_crop_to_aspect(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Center-crop img to the target aspect ratio, then resize to target size."""
    target_ratio = target_w / target_h
    w, h = img.size
    cur_ratio = w / h
    if cur_ratio > target_ratio:
        # too wide -> crop width
        new_w = int(round(h * target_ratio))
        left = (w - new_w) // 2
        box = (left, 0, left + new_w, h)
    else:
        # too tall -> crop height
        new_h = int(round(w / target_ratio))
        top = (h - new_h) // 2
        box = (0, top, w, top + new_h)
    cropped = img.crop(box)
    return cropped.resize((target_w, target_h), Image.Resampling.LANCZOS)


def _to_srgb_rgb(img: Image.Image) -> Image.Image:
    """Return an RGB image in sRGB. If an ICC profile is present, convert it."""
    icc = img.info.get("icc_profile")
    if icc:
        try:
            import io

            from PIL import ImageCms

            src = ImageCms.ImageCmsProfile(io.BytesIO(icc))
            dst = ImageCms.createProfile("sRGB")
            converted = ImageCms.profileToProfile(img, src, dst, outputMode="RGB")
            if converted is not None:
                return converted
        except Exception as exc:  # pragma: no cover - ICC edge case
            log.warning("ICC->sRGB conversion failed (%s); falling back to RGB", exc)
    return img.convert("RGB")


def process_image(image: Image.Image, cfg: Config, out_path: str | Path) -> ProcessedImage:
    if cfg.postproc.aspect not in ASPECT_DIMS:
        raise PostprocError(f"unsupported aspect {cfg.postproc.aspect}")
    target_w, target_h = ASPECT_DIMS[cfg.postproc.aspect]

    img = _to_srgb_rgb(image)
    img = center_crop_to_aspect(img, target_w, target_h)

    # Mild unsharp mask.
    img = img.filter(
        ImageFilter.UnsharpMask(
            radius=cfg.postproc.unsharp_radius,
            percent=cfg.postproc.unsharp_percent,
            threshold=cfg.postproc.unsharp_threshold,
        )
    )

    # Validate aspect window before writing.
    aspect = target_w / target_h
    if not (IG_MIN_ASPECT <= aspect <= IG_MAX_ASPECT):
        raise PostprocError(
            f"final aspect {aspect:.3f} outside Instagram range [{IG_MIN_ASPECT}, {IG_MAX_ASPECT}]"
        )

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    # Save without EXIF/ICC (strip all metadata) at quality 92.
    clean = Image.new("RGB", img.size)
    clean.putdata(list(img.getdata()))
    clean.save(out, format="JPEG", quality=cfg.postproc.jpeg_quality, optimize=True)

    data = out.read_bytes()
    size = len(data)
    if size > cfg.postproc.max_bytes:
        raise PostprocError(f"output {size} bytes exceeds max {cfg.postproc.max_bytes} bytes")

    sha = hashlib.sha256(data).hexdigest()
    log.info("processed image %dx%d, %d bytes, sha256=%s", target_w, target_h, size, sha[:12])
    return ProcessedImage(path=out, width=target_w, height=target_h, bytes=size, sha256=sha)
