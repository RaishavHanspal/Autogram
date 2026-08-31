"""CPU-friendly Instagram Reel renderer.

Turns generated still images into a genuine 1080x1920 MP4 video with:
  * randomized, seeded camera movement (zoom/pan/focal point);
  * random transitions and light visual treatments;
  * variable scene durations;
  * royalty-free music picked at random from ``reel.audio_dir`` and started at a
    random offset within the track (never always from the beginning), with fade
    in/out; a synthesized ambient bed is used when no track is available;
  * H.264 + AAC + faststart.

This animates still images. It does NOT synthesize true human/object motion —
that is the job of :mod:`autogram.render.ai_video` (whose clips are assembled by
:func:`assemble_ai_clips`).
"""

from __future__ import annotations

import random
import re
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from ..config import Config
from ..logging_utils import get_logger

log = get_logger("reel")


VIDEO_SUFFIXES = {".mp4", ".mov"}

_AUDIO_SUFFIXES = {".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"}


class ReelError(RuntimeError):
    """Raised when a Reel cannot be produced."""


# ---------------------------------------------------------------------------
# Camera / visual presets
# ---------------------------------------------------------------------------

_MOTIONS = [
    "push_in",
    "pull_out",
    "pan_left",
    "pan_right",
    "pan_up",
    "pan_down",
    "diagonal_tl",
    "diagonal_tr",
    "diagonal_bl",
    "diagonal_br",
    "orbit_left",
    "orbit_right",
    "float",
    "dramatic_push",
    "dramatic_pull",
]

_TRANSITIONS = [
    "fade",
    "fadeblack",
    "fadewhite",
    "wipeleft",
    "wiperight",
    "slideleft",
    "slideright",
    "circleopen",
    "smoothleft",
    "smoothright",
]

_EFFECTS = [
    "clean",
    "warm",
    "cinematic",
    "dreamy",
    "soft",
    "contrast",
    "vignette",
]


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------


def is_video(path: str | Path) -> bool:
    """True if the path looks like a video file."""
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


def ffmpeg_available() -> bool:
    return shutil.which("ffmpeg") is not None


def _normalize_images(image_paths: str | Path | Sequence[str | Path]) -> list[Path]:
    if isinstance(image_paths, str | Path):
        items: Sequence[str | Path] = [image_paths]
    else:
        items = image_paths
    return [Path(p) for p in items if p]


def _media_duration(path: Path) -> float:
    """Best-effort media (audio or video) duration via ffprobe; 0.0 on failure."""
    try:
        res = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "format=duration",
                "-of",
                "default=noprint_wrappers=1:nokey=1",
                str(path),
            ],
            capture_output=True,
            text=True,
            check=True,
        )
        return float(res.stdout.strip())
    except (subprocess.CalledProcessError, ValueError, OSError):
        return 0.0


def _pick_audio(
    audio_dir: str,
    rng: random.Random,
    need_seconds: float,
) -> tuple[Path, float] | None:
    """Pick a random royalty-free track and a random start offset within it.

    Returns ``(path, start_offset_seconds)`` or ``None`` when no usable track
    exists (the caller then synthesizes an ambient bed). The offset is chosen so
    the Reel starts somewhere inside the song rather than always at t=0; the
    input is still looped so a short track fills the whole Reel.
    """
    d = Path(audio_dir)
    if not d.is_dir():
        return None
    tracks = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES)
    if not tracks:
        return None

    track = rng.choice(tracks)
    dur = _media_duration(track)
    # Leave a little tail so we don't start at the very end; loop covers the rest.
    max_offset = max(0.0, dur - max(1.0, need_seconds * 0.5))
    offset = rng.uniform(0.0, max_offset) if max_offset > 0.5 else 0.0
    return track, offset


# ---------------------------------------------------------------------------
# Random scene planning
# ---------------------------------------------------------------------------


def _random_scene_plan(n: int, rc, rng: random.Random) -> list[dict]:
    """Generate a unique, still-photographic visual plan for this Reel."""
    plan: list[dict] = []
    previous_motion = None
    previous_transition = None
    previous_effect = None

    for i in range(n):
        if i == 0:
            duration = rng.uniform(max(2.8, rc.seconds_per_image - 0.6), rc.seconds_per_image + 0.7)
        else:
            duration = rng.uniform(max(2.2, rc.seconds_per_image - 0.8), rc.seconds_per_image + 0.8)

        motions = [m for m in _MOTIONS if m != previous_motion]
        motion = rng.choice(motions)

        if motion in {"dramatic_push", "dramatic_pull"}:
            zoom = rng.uniform(1.14, 1.28)
        else:
            zoom = rng.uniform(1.035, 1.14)

        focal_x = rng.uniform(0.38, 0.62)
        focal_y = rng.uniform(0.35, 0.65)

        rotation = rng.uniform(-0.006, 0.006)
        if rng.random() < 0.16:
            rotation = rng.uniform(-0.012, 0.012)

        effects = [e for e in _EFFECTS if e != previous_effect]
        effect = rng.choice(effects)

        transitions = [t for t in _TRANSITIONS if t != previous_transition]
        transition = rng.choice(transitions)
        if i == 0:
            transition = "fade"

        plan.append(
            {
                "duration": duration,
                "motion": motion,
                "zoom": zoom,
                "focal_x": focal_x,
                "focal_y": focal_y,
                "rotation": rotation,
                "effect": effect,
                "transition": transition,
            }
        )

        previous_motion = motion
        previous_transition = transition
        previous_effect = effect

    return plan


# ---------------------------------------------------------------------------
# Camera motion
# ---------------------------------------------------------------------------


def _motion_expression(motion: str, focal_x: float, focal_y: float) -> tuple[str, str]:
    """Return normalized x/y movement expressions in terms of progress 'p' (0->1)."""
    amount = 0.13
    cx = focal_x
    cy = focal_y

    if motion in {"push_in", "pull_out", "dramatic_push", "dramatic_pull"}:
        x, y = f"{cx}", f"{cy}"
    elif motion == "pan_left":
        x, y = f"{cx + amount / 2} - {amount}*p", f"{cy}"
    elif motion == "pan_right":
        x, y = f"{cx - amount / 2} + {amount}*p", f"{cy}"
    elif motion == "pan_up":
        x, y = f"{cx}", f"{cy + amount / 2} - {amount}*p"
    elif motion == "pan_down":
        x, y = f"{cx}", f"{cy - amount / 2} + {amount}*p"
    elif motion == "diagonal_tl":
        x, y = f"{cx + amount / 2} - {amount}*p", f"{cy + amount / 2} - {amount}*p"
    elif motion == "diagonal_tr":
        x, y = f"{cx - amount / 2} + {amount}*p", f"{cy + amount / 2} - {amount}*p"
    elif motion == "diagonal_bl":
        x, y = f"{cx + amount / 2} - {amount}*p", f"{cy - amount / 2} + {amount}*p"
    elif motion == "diagonal_br":
        x, y = f"{cx - amount / 2} + {amount}*p", f"{cy - amount / 2} + {amount}*p"
    elif motion == "orbit_left":
        x, y = f"{cx} + 0.045*sin(2*PI*p)", f"{cy} + 0.025*cos(2*PI*p)"
    elif motion == "orbit_right":
        x, y = f"{cx} - 0.045*sin(2*PI*p)", f"{cy} + 0.025*cos(2*PI*p)"
    elif motion == "float":
        x, y = f"{cx} + 0.025*sin(2*PI*p)", f"{cy} + 0.035*cos(2*PI*p)"
    else:
        x, y = f"{cx}", f"{cy}"

    return x, y


# ---------------------------------------------------------------------------
# Visual effects
# ---------------------------------------------------------------------------


def _effect_filter(effect: str) -> str:
    """Return a lightweight FFmpeg visual treatment."""
    if effect == "warm":
        return "eq=brightness=0.025:contrast=1.04:saturation=1.10"
    if effect == "cinematic":
        return "eq=brightness=-0.015:contrast=1.10:saturation=0.94"
    if effect == "dreamy":
        return "eq=brightness=0.025:contrast=0.96:saturation=1.05,gblur=sigma=0.35"
    if effect == "soft":
        return "eq=brightness=0.015:contrast=0.98:saturation=1.02,unsharp=5:5:0.35:5:5:0"
    if effect == "contrast":
        return "eq=brightness=-0.01:contrast=1.15:saturation=1.04"
    if effect == "vignette":
        return "eq=brightness=0.01:contrast=1.05:saturation=1.03,vignette=PI/5"
    return ""


# ---------------------------------------------------------------------------
# Scene filter
# ---------------------------------------------------------------------------


def _scene_filter(
    idx: int,
    width: int,
    height: int,
    fps: int,
    frames: int,
    scene: dict,
) -> str:
    """Build a single animated scene: oversize, then zoompan through it."""
    up_w = width * 2
    up_h = height * 2

    zoom = float(scene["zoom"])
    motion = scene["motion"]
    effect = scene["effect"]

    # zoompan has a frame counter 'on'; p is normalized progress from 0 -> 1.
    progress = f"(on/{max(frames - 1, 1)})"

    x_expr, y_expr = _motion_expression(motion, float(scene["focal_x"]), float(scene["focal_y"]))

    # The motion expressions are in terms of 'p'; zoompan has no 'p' variable, so
    # substitute the concrete progress in terms of its frame counter 'on'. \bp\b
    # avoids touching PI/pow/etc.
    x_expr = re.sub(r"\bp\b", progress, x_expr)
    y_expr = re.sub(r"\bp\b", progress, y_expr)

    # Convert normalized coordinates to actual coordinates (iw/ih = source dims
    # after scaling). NOTE: both expressions need the '+' between the base offset
    # and the focal term — a missing '+' makes ffmpeg reject the filter and the
    # whole Reel silently falls back to a still image.
    x_expr = f"(iw/2-(iw/zoom/2))+(({x_expr})-0.5)*iw/zoom"
    y_expr = f"(ih/2-(ih/zoom/2))+(({y_expr})-0.5)*ih/zoom"

    if motion == "push_in":
        zoom_expr = f"1+({zoom - 1:.5f})*({progress})"
    elif motion == "pull_out":
        zoom_expr = f"{zoom:.5f}-({zoom - 1:.5f})*({progress})"
    elif motion == "dramatic_push":
        zoom_expr = f"1+({zoom - 1:.5f})*pow({progress},0.72)"
    elif motion == "dramatic_pull":
        zoom_expr = f"{zoom:.5f}-({zoom - 1:.5f})*pow({progress},0.72)"
    else:
        zoom_expr = f"1+({zoom - 1:.5f})*({progress})+0.006*sin(2*PI*{progress})"

    filters = [
        f"scale={up_w}:{up_h}:force_original_aspect_ratio=increase",
        f"crop={up_w}:{up_h}",
        (
            "zoompan="
            f"z='{zoom_expr}':"
            f"x='{x_expr}':"
            f"y='{y_expr}':"
            f"d={frames}:"
            f"s={width}x{height}:"
            f"fps={fps}"
        ),
    ]

    effect_filter = _effect_filter(effect)
    if effect_filter:
        filters.append(effect_filter)

    filters.extend(["setsar=1", f"fps={fps}", "format=yuv420p", "setpts=PTS-STARTPTS"])
    return f"[{idx}:v]" + ",".join(filters) + f"[v{idx}]"


# ---------------------------------------------------------------------------
# Filter graph
# ---------------------------------------------------------------------------


def _build_filtergraph(scenes: list[dict], cfg: Config) -> tuple[str, str]:
    """Build the complete video filter graph; return (graph, output_label)."""
    rc = cfg.reel
    parts: list[str] = []

    frame_counts = [max(1, int(round(scene["duration"] * rc.fps))) for scene in scenes]

    for idx, scene in enumerate(scenes):
        parts.append(
            _scene_filter(
                idx=idx,
                width=rc.width,
                height=rc.height,
                fps=rc.fps,
                frames=frame_counts[idx],
                scene=scene,
            )
        )

    if len(scenes) == 1:
        return ";".join(parts), "v0"

    previous = "v0"
    accumulated = scenes[0]["duration"]

    for i in range(1, len(scenes)):
        transition = scenes[i]["transition"]
        crossfade = min(
            float(rc.crossfade_s),
            float(scenes[i - 1]["duration"]) * 0.35,
            float(scenes[i]["duration"]) * 0.35,
        )
        offset = accumulated - crossfade
        label = "vout" if i == len(scenes) - 1 else f"x{i}"
        parts.append(
            f"[{previous}][v{i}]"
            f"xfade=transition={transition}:duration={crossfade:.3f}:offset={offset:.3f}"
            f"[{label}]"
        )
        previous = label
        accumulated += scenes[i]["duration"] - crossfade

    return ";".join(parts), "vout"


# ---------------------------------------------------------------------------
# Audio
# ---------------------------------------------------------------------------


def _fade_params(duration: float) -> tuple[float, float, float]:
    """Return (fade_in, fade_out, fade_out_start) proportional to duration."""
    fade_in = min(1.2, max(0.25, duration * 0.08))
    fade_out = min(1.8, max(0.4, duration * 0.12))
    fade_out_start = max(0.0, duration - fade_out)
    return fade_in, fade_out, fade_out_start


def _external_audio_filter(audio_idx: int, duration: float) -> str:
    """Filtergraph branch that fades/levels a looped external track to [aout]."""
    fade_in, fade_out, fade_out_start = _fade_params(duration)
    return (
        f"[{audio_idx}:a]"
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f},"
        "volume=0.85,"
        "aresample=44100"
        "[aout]"
    )


def _build_generated_audio(duration: float, rng: random.Random) -> str:
    """Synthesize a unique ambient/cinematic music bed via FFmpeg aevalsrc."""
    roots = [196.0, 207.65, 220.0, 233.08, 246.94, 261.63, 277.18, 293.66, 311.13, 329.63, 349.23]
    root = rng.choice(roots)

    interval_sets = [
        (1.0, 1.25, 1.50),
        (1.0, 1.20, 1.50),
        (1.0, 1.3333, 1.6667),
        (1.0, 1.125, 1.50),
    ]
    a, b, c = rng.choice(interval_sets)

    bpm = rng.choice([68, 72, 76, 80, 84, 88, 92])
    pulse = bpm / 60.0

    amp1 = rng.uniform(0.11, 0.17)
    amp2 = rng.uniform(0.07, 0.12)
    amp3 = rng.uniform(0.055, 0.10)

    shimmer_freq = rng.uniform(880, 1320)
    shimmer_amp = rng.uniform(0.008, 0.018)
    low_freq = rng.uniform(65, 95)

    expression = (
        f"(0.82+0.18*sin(2*PI*0.11*t))*("
        f"{amp1:.4f}*sin(2*PI*{root:.3f}*t)"
        f"+{amp2:.4f}*sin(2*PI*{root * a:.3f}*t)"
        f"+{amp3:.4f}*sin(2*PI*{root * b:.3f}*t)"
        f"+{amp3 * 0.75:.4f}*sin(2*PI*{root * c:.3f}*t)"
        f")"
        f"+({shimmer_amp:.4f}*sin(2*PI*{shimmer_freq:.2f}*t)*(0.5+0.5*sin(2*PI*0.07*t)))"
        f"+(0.035*exp(-24*mod(t*{pulse:.5f},1))*sin(2*PI*{low_freq:.2f}*t))"
    )
    return f"aevalsrc='{expression}':s=44100:d={duration:.3f}"


def _build_generated_audio_filter(duration: float, rng: random.Random) -> str:
    """Generated ambient source, faded/levelled — used as an lavfi input."""
    audio_source = _build_generated_audio(duration=duration, rng=rng)
    fade_in, fade_out, fade_out_start = _fade_params(duration)
    return (
        f"{audio_source},"
        f"afade=t=in:st=0:d={fade_in:.3f},"
        f"afade=t=out:st={fade_out_start:.3f}:d={fade_out:.3f},"
        "highpass=f=55,"
        "lowpass=f=11000,"
        "volume=0.78,"
        "aresample=44100"
    )


# ---------------------------------------------------------------------------
# Main renderer
# ---------------------------------------------------------------------------


def build_reel(
    image_paths: str | Path | Sequence[str | Path],
    cfg: Config,
    out_path: str | Path,
    seed: int = 0,
) -> Path:
    """Render a unique 1080x1920 Reel from still images."""
    if not ffmpeg_available():
        raise ReelError("ffmpeg not found on PATH; cannot build a Reel")

    imgs = _normalize_images(image_paths)
    if not imgs:
        raise ReelError("no images supplied for the Reel")
    missing = [str(p) for p in imgs if not p.exists()]
    if missing:
        raise ReelError("image(s) not found: " + ", ".join(missing))

    rc = cfg.reel
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)

    if seed == 0:
        seed = random.SystemRandom().randrange(1, 2_147_483_647)
    rng = random.Random(seed)

    scenes = _random_scene_plan(n=len(imgs), rc=rc, rng=rng)

    total = sum(scene["duration"] for scene in scenes)
    for i in range(1, len(scenes)):
        crossfade = min(
            float(rc.crossfade_s),
            scenes[i - 1]["duration"] * 0.35,
            scenes[i]["duration"] * 0.35,
        )
        total -= crossfade
    total = max(1.0, total)

    audio = _pick_audio(rc.audio_dir, rng, need_seconds=total)

    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for idx, image in enumerate(imgs):
        cmd += ["-loop", "1", "-t", f"{scenes[idx]['duration']:.3f}", "-i", str(image)]

    audio_idx = len(imgs)
    if audio is not None:
        track, offset = audio
        # -ss before -i seeks into the track; -stream_loop still fills the Reel.
        cmd += ["-stream_loop", "-1", "-ss", f"{offset:.3f}", "-i", str(track)]
    else:
        cmd += ["-f", "lavfi", "-i", _build_generated_audio_filter(duration=total, rng=rng)]

    filter_complex, video_label = _build_filtergraph(scenes=scenes, cfg=cfg)
    if audio is not None:
        # Fade/level the external track inside the graph -> [aout].
        filter_complex = f"{filter_complex};{_external_audio_filter(audio_idx, total)}"
        audio_map = "[aout]"
    else:
        audio_map = f"{audio_idx}:a"

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        f"[{video_label}]",
        "-map",
        audio_map,
        "-t",
        f"{total:.3f}",
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
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
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out),
    ]

    log.info(
        "building reel: seed=%d scenes=%d duration=%.2fs %dx%d fps=%d audio=%s%s",
        seed,
        len(imgs),
        total,
        rc.width,
        rc.height,
        rc.fps,
        audio[0].name if audio else "generated-ambient",
        f" offset={audio[1]:.1f}s" if audio else "",
    )

    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace")[-4000:] if exc.stderr else str(exc)
        raise ReelError("ffmpeg failed to assemble the Reel:\n" + detail) from exc

    if not out.exists():
        raise ReelError(f"ffmpeg completed but output was not created: {out}")
    if out.stat().st_size < 50_000:
        raise ReelError(f"generated Reel appears invalid or empty: {out}")

    log.info("reel created: %s (%.2f MB)", out, out.stat().st_size / (1024 * 1024))
    return out


def assemble_ai_clips(
    clips: Sequence[str | Path],
    cfg: Config,
    out_path: str | Path,
    seed: int = 0,
) -> Path:
    """Assemble AI-generated video clips (real motion) into a final Reel.

    The clips already contain motion, so each is only normalized to WxH and
    hard-concatenated (robust to varying provider clip lengths), then audio is
    muxed: a royalty-free track (random file + random start offset, faded) when
    available, else a synthesized ambient bed. H.264 + AAC + faststart.
    """
    if not ffmpeg_available():
        raise ReelError("ffmpeg not found on PATH; cannot assemble AI clips")
    vids = [Path(c) for c in clips if c]
    if not vids:
        raise ReelError("no AI clips supplied")

    rc = cfg.reel
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    rng = random.Random(seed)

    total = sum(_media_duration(v) for v in vids)
    if total <= 0:
        total = len(vids) * float(cfg.reel.ai_video.duration_s)

    audio = _pick_audio(rc.audio_dir, rng, need_seconds=total)

    cmd: list[str] = ["ffmpeg", "-y", "-hide_banner", "-loglevel", "error"]
    for v in vids:
        cmd += ["-i", str(v)]

    audio_idx = len(vids)
    if audio is not None:
        track, offset = audio
        cmd += ["-stream_loop", "-1", "-ss", f"{offset:.3f}", "-i", str(track)]
    else:
        cmd += ["-f", "lavfi", "-i", _build_generated_audio_filter(duration=total + 2.0, rng=rng)]

    parts = [
        f"[{i}:v]scale={rc.width}:{rc.height}:force_original_aspect_ratio=increase,"
        f"crop={rc.width}:{rc.height},setsar=1,fps={rc.fps},format=yuv420p,"
        f"setpts=PTS-STARTPTS[v{i}]"
        for i in range(len(vids))
    ]
    concat_inputs = "".join(f"[v{i}]" for i in range(len(vids)))
    parts.append(f"{concat_inputs}concat=n={len(vids)}:v=1:a=0[vout]")

    if audio is not None:
        parts.append(_external_audio_filter(audio_idx, total))
        audio_map = "[aout]"
    else:
        audio_map = f"{audio_idx}:a"

    filter_complex = ";".join(parts)

    cmd += [
        "-filter_complex",
        filter_complex,
        "-map",
        "[vout]",
        "-map",
        audio_map,
        "-c:v",
        "libx264",
        "-preset",
        "veryfast",
        "-crf",
        "20",
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
        "-ac",
        "2",
        "-movflags",
        "+faststart",
        "-shortest",
        str(out),
    ]

    log.info(
        "assembling reel from %d AI clip(s): %s audio=%s%s",
        len(vids),
        out,
        audio[0].name if audio else "generated-ambient",
        f" offset={audio[1]:.1f}s" if audio else "",
    )
    try:
        subprocess.run(cmd, check=True, capture_output=True)
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", "replace")[-2000:] if exc.stderr else str(exc)
        raise ReelError("ffmpeg failed to assemble AI clips:\n" + detail) from exc
    if not out.exists() or out.stat().st_size < 50_000:
        raise ReelError(f"assembled AI reel appears invalid: {out}")
    return out
