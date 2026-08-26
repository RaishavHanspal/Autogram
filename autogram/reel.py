"""Assemble a proper vertical Instagram Reel (mp4) from generated stills.

Free-tier / CPU friendly: no video model. The run generates several stills of
the SAME couple in different places, and this module stitches them into a real
1080x1920 Reel — a Ken-Burns pan/zoom per scene, crossfades between scenes, and
an audio track — encoded H.264 + AAC with ``+faststart`` so Instagram accepts it
as a clean Reel (a silent, non-conformant file is what made earlier uploads look
like a scaled still and drop their caption).

Audio: if royalty-free tracks exist in ``reel.audio_dir`` one is muxed in;
otherwise a soft self-generated ambient bed is synthesized so the Reel is never
silent (silent Reels get almost no reach and confuse the clip uploader).
Instagram's own licensed/"suggested" music cannot be attached via the free API,
so drop your own CC0/royalty-free tracks in ``reel.audio_dir`` for real music.
"""

from __future__ import annotations

import random
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .config import Config
from .logging_utils import get_logger

log = get_logger("reel")

VIDEO_SUFFIXES = {".mp4", ".mov"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}

# Ken-Burns pan directions (pixels of drift), cycled per scene for variety.
_PAN_DIRS = [(-80, 0), (80, -60), (0, 80), (80, 60), (-80, -60), (0, -80)]

# Soft A-major-ish drone with a slow tremolo — pleasant, royalty-free, legal.
_AMBIENT_LAVFI = (
    "aevalsrc='(0.9+0.1*sin(2*PI*0.2*t))*"
    "(0.18*sin(2*PI*220*t)+0.14*sin(2*PI*277*t)+0.11*sin(2*PI*330*t))':s=44100"
)


class ReelError(RuntimeError):
    """Raised when a Reel cannot be produced (e.g. ffmpeg unavailable)."""


def is_video(path: str | Path) -> bool:
    """True if the path looks like a video file (used to pick the upload API)."""
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _pick_audio(audio_dir: str, rng: random.Random) -> Path | None:
    """Pick one royalty-free track from audio_dir, or None if the dir is empty."""
    d = Path(audio_dir)
    if not d.is_dir():
        return None
    tracks = sorted(p for p in d.iterdir() if p.suffix.lower() in _AUDIO_SUFFIXES)
    return rng.choice(tracks) if tracks else None


def _kenburns_clip(idx: int, width: int, height: int, fps: int, frames: int, zoom: float) -> str:
    """filter_complex segment: input idx -> a Ken-Burns [v{idx}] stream."""
    up_w, up_h = width * 2, height * 2
    dx, dy = _PAN_DIRS[idx % len(_PAN_DIRS)]
    return (
        f"[{idx}:v]scale={up_w}:{up_h}:force_original_aspect_ratio=increase,"
        f"crop={up_w}:{up_h},"
        f"zoompan=z='min(1+{zoom - 1:.4f}*on/{frames},{zoom:.4f})':"
        f"x='iw/2-(iw/zoom/2)+{dx}':y='ih/2-(ih/zoom/2)+{dy}':"
        f"d={frames}:s={width}x{height}:fps={fps},"
        f"setpts=PTS-STARTPTS,fps={fps},format=yuv420p[v{idx}]"
    )


def _build_filtergraph(n: int, cfg: Config, frames: int) -> tuple[str, str]:
    """Return (filter_complex, final_video_label) for n scenes."""
    rc = cfg.reel
    parts = [_kenburns_clip(i, rc.width, rc.height, rc.fps, frames, rc.zoom) for i in range(n)]
    if n == 1:
        return ";".join(parts), "v0"
    prev = "v0"
    for i in range(1, n):
        offset = i * (rc.seconds_per_image - rc.crossfade_s)
        label = "vout" if i == n - 1 else f"x{i}"
        parts.append(
            f"[{prev}][v{i}]xfade=transition=fade:"
            f"duration={rc.crossfade_s}:offset={offset:.3f}[{label}]"
        )
        prev = label
    return ";".join(parts), "vout"


def _normalize_images(image_paths: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(image_paths, str | Path):
        items: Sequence[str | Path] = [image_paths]
    else:
        items = image_paths
    return [Path(p) for p in items if p]


def build_reel(
    image_paths: str | Path | Sequence[str | Path],
    cfg: Config,
    out_path: str | Path,
    seed: int = 0,
) -> Path:
    """Render a 1080x1920 Reel mp4 from one or more stills. Returns the path.

    Raises ReelError only when ffmpeg is unavailable or no images are given.
    """
    if not ffmpeg_available():
        raise ReelError("ffmpeg not found on PATH; cannot build a Reel")
    imgs = _normalize_images(image_paths)
    if not imgs:
        raise ReelError("no images supplied for the Reel")

    rc = cfg.reel
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frames = max(1, int(rc.seconds_per_image * rc.fps))
    xfade = rc.crossfade_s if len(imgs) > 1 else 0.0
    total = len(imgs) * rc.seconds_per_image - (len(imgs) - 1) * xfade

    rng = random.Random(seed)
    audio = _pick_audio(rc.audio_dir, rng)

    cmd: list[str] = ["ffmpeg", "-y"]
    for p in imgs:
        cmd += ["-loop", "1", "-t", str(rc.seconds_per_image), "-i", str(p)]
    audio_idx = len(imgs)
    if audio is not None:
        cmd += ["-stream_loop", "-1", "-i", str(audio)]
    else:
        cmd += ["-f", "lavfi", "-i", _AMBIENT_LAVFI]

    fc, vlabel = _build_filtergraph(len(imgs), cfg, frames)
    cmd += [
        "-filter_complex",
        fc,
        "-map",
        f"[{vlabel}]",
        "-map",
        f"{audio_idx}:a",
        "-t",
        f"{total:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
        "-r",
        str(rc.fps),
        "-c:a",
        "aac",
        "-b:a",
        "128k",
        "-ar",
        "44100",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out),
    ]

    log.info(
        "building reel: %d scene(s), %.1fs, %dx%d, %dfps, audio=%s",
        len(imgs),
        total,
        rc.width,
        rc.height,
        rc.fps,
        audio.name if audio else "generated-ambient",
    )
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace")[-500:] if exc.stderr else str(exc)
        raise ReelError(f"ffmpeg failed to assemble the reel: {detail}") from exc
    return out