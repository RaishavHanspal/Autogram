"""Assemble a vertical Instagram Reel (mp4) from a single generated still.

Free-tier / CPU friendly: no video model is used. We take the already-generated
still of the couple and render a slow Ken-Burns zoom to 1080x1920 H.264/AAC,
optionally muxing a royalty-free audio track. This keeps the same pipeline and
the same posting path — only the media file changes from .jpg to .mp4.

Audio note: Instagram's own licensed/suggested music cannot be attached through
the free (private or Graph) API, and using copyrighted tracks violates ToS. So
bring your own CC0/royalty-free tracks: drop .mp3/.wav files into the configured
``reel.audio_dir`` (default ``assets/audio``). If none are present the Reel is
posted silently (still valid; audio just helps reach).
"""

from __future__ import annotations

import random
import shutil
import subprocess
from pathlib import Path

from .config import Config
from .logging_utils import get_logger

log = get_logger("reel")

VIDEO_SUFFIXES = {".mp4", ".mov"}
_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg"}


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


def _kenburns_vf(width: int, height: int, total_frames: int, fps: int, zoom: float) -> str:
    """ffmpeg -vf for a smooth slow zoom, cover-cropped to width x height."""
    up_w, up_h = width * 2, height * 2
    return (
        f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase,"
        f"crop={up_w}:{up_h},"
        f"zoompan=z='min(1+({zoom - 1})*on/{total_frames},{zoom})':"
        f"x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
        f"d={total_frames}:s={width}x{height}:fps={fps},"
        f"format=yuv420p"
    )


def _static_vf(width: int, height: int) -> str:
    """Robust fallback filter: cover-crop the still, no zoom."""
    return (
        f"scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},format=yuv420p"
    )


def _run_ffmpeg(image_path: Path, out: Path, cfg: Config, audio: Path | None, vf: str) -> None:
    rc = cfg.reel
    cmd: list[str] = ["ffmpeg", "-y", "-loop", "1", "-i", str(image_path)]
    if audio is not None:
        cmd += ["-stream_loop", "-1", "-i", str(audio)]
    cmd += [
        "-t",
        str(rc.duration_s),
        "-r",
        str(rc.fps),
        "-vf",
        vf,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-pix_fmt",
        "yuv420p",
    ]
    if audio is not None:
        cmd += ["-c:a", "aac", "-b:a", "128k", "-shortest", "-map", "0:v:0", "-map", "1:a:0"]
    else:
        cmd += ["-an"]
    cmd += [str(out)]
    subprocess.run(cmd, check=True, capture_output=True)


def build_reel(
    image_path: str | Path,
    cfg: Config,
    out_path: str | Path,
    seed: int = 0,
) -> Path:
    """Render a 1080x1920 Reel mp4 from a still. Returns the output path.

    Ken-Burns is attempted first; if that ffmpeg invocation fails for any
    reason we fall back to a dead-simple static render so a run never dies on a
    finicky filter. Raises ReelError only when ffmpeg is entirely unavailable.
    """
    if not ffmpeg_available():
        raise ReelError("ffmpeg not found on PATH; cannot build a Reel")

    rc = cfg.reel
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    total_frames = max(1, int(rc.fps * rc.duration_s))
    rng = random.Random(seed)
    audio = _pick_audio(rc.audio_dir, rng) if rc.audio_dir else None

    log.info(
        "building reel %dx%d %.1fs %dfps audio=%s",
        rc.width,
        rc.height,
        rc.duration_s,
        rc.fps,
        audio.name if audio else "none",
    )
    kb_vf = _kenburns_vf(rc.width, rc.height, total_frames, rc.fps, rc.zoom)
    try:
        _run_ffmpeg(Path(image_path), out, cfg, audio, kb_vf)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace")[-300:] if exc.stderr else str(exc)
        log.warning("ken-burns render failed (%s); falling back to static render", detail)
        _run_ffmpeg(Path(image_path), out, cfg, audio, _static_vf(rc.width, rc.height))
    return out