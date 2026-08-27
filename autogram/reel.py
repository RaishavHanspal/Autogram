"""
CPU-friendly Instagram Reel renderer.

Turns generated still images into a genuine 1080x1920 MP4 video.

Features:
- Randomized camera movement
- Random zoom/pan/focal point
- Subtle rotation
- Random visual treatments
- Random transitions
- Variable scene durations
- Seeded per-Reel uniqueness
- Generated royalty-free ambient/music-like audio
- Optional royalty-free audio tracks from reel.audio_dir
- Beat/pulse timing derived from the generated soundtrack
- H.264 + AAC + faststart

NOTE:
This creates animated video from still images. It does NOT generate
true human/object motion like an AI image-to-video model.
"""

from __future__ import annotations

import math
import random
import shutil
import subprocess
from collections.abc import Sequence
from pathlib import Path

from .config import Config
from .logging_utils import get_logger

log = get_logger("reel")


VIDEO_SUFFIXES = {".mp4", ".mov"}

_AUDIO_SUFFIXES = {
    ".mp3",
    ".wav",
    ".m4a",
    ".aac",
    ".ogg",
    ".flac",
}


class ReelError(RuntimeError):
    """Raised when a Reel cannot be produced."""


# ---------------------------------------------------------------------------
# Camera / visual presets
# ---------------------------------------------------------------------------

# Movement is expressed as normalized offsets rather than fixed pixels.
# This makes the effect work better across different resolutions.
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


def _normalize_images(
    image_paths: str | Path | Sequence[str | Path],
) -> list[Path]:
    if isinstance(image_paths, (str, Path)):
        items: Sequence[str | Path] = [image_paths]
    else:
        items = image_paths

    return [Path(p) for p in items if p]


def _pick_audio(
    audio_dir: str,
    rng: random.Random,
) -> Path | None:
    """
    Pick a random royalty-free audio file.

    If no valid audio exists, the Reel uses generated audio.
    """
    d = Path(audio_dir)

    if not d.is_dir():
        return None

    tracks = sorted(
        p for p in d.iterdir()
        if p.is_file() and p.suffix.lower() in _AUDIO_SUFFIXES
    )

    if not tracks:
        return None

    return rng.choice(tracks)


# ---------------------------------------------------------------------------
# Random scene planning
# ---------------------------------------------------------------------------

def _random_scene_plan(
    n: int,
    rc,
    rng: random.Random,
) -> list[dict]:
    """
    Generate a unique visual plan for this Reel.

    We intentionally avoid completely random values. Instead, values are
    constrained to ranges that still look like intentional photography.
    """

    plan: list[dict] = []

    previous_motion = None
    previous_transition = None
    previous_effect = None

    for i in range(n):
        # ---------------------------------------------------------------
        # Duration
        # ---------------------------------------------------------------
        # First/last scenes are slightly longer on average.
        if i == 0:
            duration = rng.uniform(
                max(2.8, rc.seconds_per_image - 0.6),
                rc.seconds_per_image + 0.7,
            )
        else:
            duration = rng.uniform(
                max(2.2, rc.seconds_per_image - 0.8),
                rc.seconds_per_image + 0.8,
            )

        # ---------------------------------------------------------------
        # Motion
        # ---------------------------------------------------------------
        motions = [m for m in _MOTIONS if m != previous_motion]
        motion = rng.choice(motions)

        # ---------------------------------------------------------------
        # Zoom
        # ---------------------------------------------------------------
        if motion in {"dramatic_push", "dramatic_pull"}:
            zoom = rng.uniform(1.14, 1.28)
        else:
            zoom = rng.uniform(1.035, 1.14)

        # ---------------------------------------------------------------
        # Focal point
        # ---------------------------------------------------------------
        # Avoid always centering the couple.
        focal_x = rng.uniform(0.38, 0.62)
        focal_y = rng.uniform(0.35, 0.65)

        # ---------------------------------------------------------------
        # Rotation
        # ---------------------------------------------------------------
        rotation = rng.uniform(-0.006, 0.006)

        # Occasionally use a more noticeable cinematic tilt.
        if rng.random() < 0.16:
            rotation = rng.uniform(-0.012, 0.012)

        # ---------------------------------------------------------------
        # Effect
        # ---------------------------------------------------------------
        effects = [e for e in _EFFECTS if e != previous_effect]
        effect = rng.choice(effects)

        # ---------------------------------------------------------------
        # Transition
        # ---------------------------------------------------------------
        transitions = [
            t for t in _TRANSITIONS
            if t != previous_transition
        ]

        transition = rng.choice(transitions)

        # Keep the first scene simple.
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

def _motion_expression(
    motion: str,
    focal_x: float,
    focal_y: float,
) -> tuple[str, str]:
    """
    Return normalized x/y movement expressions.

    'p' is progress from 0 -> 1.
    """

    # Maximum movement in normalized image coordinates.
    amount = 0.13

    cx = focal_x
    cy = focal_y

    if motion == "push_in":
        x = f"{cx}"
        y = f"{cy}"

    elif motion == "pull_out":
        x = f"{cx}"
        y = f"{cy}"

    elif motion == "pan_left":
        x = f"{cx + amount / 2} - {amount}*p"
        y = f"{cy}"

    elif motion == "pan_right":
        x = f"{cx - amount / 2} + {amount}*p"
        y = f"{cy}"

    elif motion == "pan_up":
        x = f"{cx}"
        y = f"{cy + amount / 2} - {amount}*p"

    elif motion == "pan_down":
        x = f"{cx}"
        y = f"{cy - amount / 2} + {amount}*p"

    elif motion == "diagonal_tl":
        x = f"{cx + amount / 2} - {amount}*p"
        y = f"{cy + amount / 2} - {amount}*p"

    elif motion == "diagonal_tr":
        x = f"{cx - amount / 2} + {amount}*p"
        y = f"{cy + amount / 2} - {amount}*p"

    elif motion == "diagonal_bl":
        x = f"{cx + amount / 2} - {amount}*p"
        y = f"{cy - amount / 2} + {amount}*p"

    elif motion == "diagonal_br":
        x = f"{cx - amount / 2} + {amount}*p"
        y = f"{cy - amount / 2} + {amount}*p"

    elif motion == "orbit_left":
        x = f"{cx} + 0.045*sin(2*PI*p)"
        y = f"{cy} + 0.025*cos(2*PI*p)"

    elif motion == "orbit_right":
        x = f"{cx} - 0.045*sin(2*PI*p)"
        y = f"{cy} + 0.025*cos(2*PI*p)"

    elif motion == "float":
        x = f"{cx} + 0.025*sin(2*PI*p)"
        y = f"{cy} + 0.035*cos(2*PI*p)"

    elif motion == "dramatic_push":
        x = f"{cx}"
        y = f"{cy}"

    elif motion == "dramatic_pull":
        x = f"{cx}"
        y = f"{cy}"

    else:
        x = f"{cx}"
        y = f"{cy}"

    return x, y


# ---------------------------------------------------------------------------
# Visual effects
# ---------------------------------------------------------------------------

def _effect_filter(effect: str) -> str:
    """Return a lightweight FFmpeg visual treatment."""

    if effect == "clean":
        return ""

    if effect == "warm":
        return (
            "eq="
            "brightness=0.025:"
            "contrast=1.04:"
            "saturation=1.10"
        )

    if effect == "cinematic":
        return (
            "eq="
            "brightness=-0.015:"
            "contrast=1.10:"
            "saturation=0.94"
        )

    if effect == "dreamy":
        return (
            "eq="
            "brightness=0.025:"
            "contrast=0.96:"
            "saturation=1.05,"
            "gblur=sigma=0.35"
        )

    if effect == "soft":
        return (
            "eq="
            "brightness=0.015:"
            "contrast=0.98:"
            "saturation=1.02,"
            "unsharp=5:5:0.35:5:5:0"
        )

    if effect == "contrast":
        return (
            "eq="
            "brightness=-0.01:"
            "contrast=1.15:"
            "saturation=1.04"
        )

    if effect == "vignette":
        return (
            "eq="
            "brightness=0.01:"
            "contrast=1.05:"
            "saturation=1.03,"
            "vignette=PI/5"
        )

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
    """
    Build a single animated scene.

    The image is oversized, then zoompan continuously moves through it.
    """

    # Work on a larger canvas before cropping.
    up_w = width * 2
    up_h = height * 2

    duration = float(scene["duration"])
    zoom = float(scene["zoom"])

    focal_x = float(scene["focal_x"])
    focal_y = float(scene["focal_y"])

    motion = scene["motion"]
    rotation = float(scene["rotation"])
    effect = scene["effect"]

    # zoompan has a frame counter "on".
    # p is normalized progress from 0 -> 1.
    progress = f"(on/{max(frames - 1, 1)})"

    x_expr, y_expr = _motion_expression(
        motion,
        focal_x,
        focal_y,
    )

    # Convert normalized coordinates to actual coordinates.
    #
    # zoompan's iw/ih refer to the source dimensions after scaling.
    x_expr = (
        f"(iw/2-(iw/zoom/2))"
        f"+(({x_expr})-0.5)*iw/zoom"
    )

    y_expr = (
        f"(ih/2-(ih/zoom/2))"
        f"+(({y_expr})-0.5)*ih/zoom"
    )

    # Different motion styles use different zoom curves.
    if motion == "push_in":
        zoom_expr = (
            f"1+({zoom - 1:.5f})*"
            f"({progress})"
        )

    elif motion == "pull_out":
        zoom_expr = (
            f"{zoom:.5f}-({zoom - 1:.5f})*"
            f"({progress})"
        )

    elif motion == "dramatic_push":
        zoom_expr = (
            f"1+({zoom - 1:.5f})*"
            f"pow({progress},0.72)"
        )

    elif motion == "dramatic_pull":
        zoom_expr = (
            f"{zoom:.5f}-({zoom - 1:.5f})*"
            f"pow({progress},0.72)"
        )

    else:
        # Subtle breathing motion.
        zoom_expr = (
            f"1+({zoom - 1:.5f})*"
            f"({progress})"
            f"+0.006*sin(2*PI*{progress})"
        )

    filters = [
        f"scale={up_w}:{up_h}:"
        "force_original_aspect_ratio=increase",
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

    # Very subtle rotation.
    if abs(rotation) > 0.0001:
        filters.append(
            f"rotate="
            f"{rotation}*sin(2*PI*{progress}):"
            "fillcolor=black@0"
        )

    effect = _effect_filter(effect)
    if effect:
        filters.append(effect)

    filters.extend(
        [
            "setsar=1",
            f"fps={fps}",
            "format=yuv420p",
            "setpts=PTS-STARTPTS",
        ]
    )

    return (
        f"[{idx}:v]"
        + ",".join(filters)
        + f"[v{idx}]"
    )


# ---------------------------------------------------------------------------
# Filter graph
# ---------------------------------------------------------------------------

def _build_filtergraph(
    scenes: list[dict],
    cfg: Config,
) -> tuple[str, str]:
    """
    Build the complete video filter graph.
    """

    rc = cfg.reel

    parts: list[str] = []

    frame_counts = [
        max(
            1,
            int(round(scene["duration"] * rc.fps)),
        )
        for scene in scenes
    ]

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

        # Keep transitions short enough for short scenes.
        crossfade = min(
            float(rc.crossfade_s),
            float(scenes[i - 1]["duration"]) * 0.35,
            float(scenes[i]["duration"]) * 0.35,
        )

        offset = accumulated - crossfade

        label = (
            "vout"
            if i == len(scenes) - 1
            else f"x{i}"
        )

        parts.append(
            f"[{previous}][v{i}]"
            f"xfade="
            f"transition={transition}:"
            f"duration={crossfade:.3f}:"
            f"offset={offset:.3f}"
            f"[{label}]"
        )

        previous = label
        accumulated += scenes[i]["duration"] - crossfade

    return ";".join(parts), "vout"


# ---------------------------------------------------------------------------
# Generated audio
# ---------------------------------------------------------------------------

def _build_generated_audio(
    duration: float,
    rng: random.Random,
) -> str:
    """
    Generate a unique ambient/cinematic music bed using FFmpeg's aevalsrc.

    No downloaded music is required.

    Each Reel gets:
    - different root note
    - different chord interval
    - different BPM
    - different pulse frequency
    - different shimmer
    - different low-frequency movement
    """

    roots = [
        196.00,   # G3
        207.65,   # Ab3
        220.00,   # A3
        233.08,   # Bb3
        246.94,   # B3
        261.63,   # C4
        277.18,   # Db4
        293.66,   # D4
        311.13,   # Eb4
        329.63,   # E4
        349.23,   # F4
    ]

    root = rng.choice(roots)

    # Major-ish or suspended intervals.
    interval_sets = [
        (1.0, 1.25, 1.50),
        (1.0, 1.20, 1.50),
        (1.0, 1.3333, 1.6667),
        (1.0, 1.125, 1.50),
    ]

    a, b, c = rng.choice(interval_sets)

    bpm = rng.choice(
        [68, 72, 76, 80, 84, 88, 92]
    )

    pulse = bpm / 60.0

    # Randomize harmonic strength.
    amp1 = rng.uniform(0.11, 0.17)
    amp2 = rng.uniform(0.07, 0.12)
    amp3 = rng.uniform(0.055, 0.10)

    shimmer_freq = rng.uniform(880, 1320)
    shimmer_amp = rng.uniform(0.008, 0.018)

    # Low-frequency pulse.
    low_freq = rng.uniform(65, 95)

    # The expression is deliberately soft so AAC encoding does not clip.
    expression = (
        f"(0.82+0.18*sin(2*PI*0.11*t))*("
        f"{amp1:.4f}*sin(2*PI*{root:.3f}*t)"
        f"+{amp2:.4f}*sin(2*PI*{root*a:.3f}*t)"
        f"+{amp3:.4f}*sin(2*PI*{root*b:.3f}*t)"
        f"+{amp3 * 0.75:.4f}*sin(2*PI*{root*c:.3f}*t)"
        f")"
        f"+"
        f"({shimmer_amp:.4f}*"
        f"sin(2*PI*{shimmer_freq:.2f}*t)*"
        f"(0.5+0.5*sin(2*PI*0.07*t)))"
        f"+"
        f"(0.035*"
        f"exp(-24*mod(t*{pulse:.5f},1))*"
        f"sin(2*PI*{low_freq:.2f}*t))"
    )

    return (
        "aevalsrc="
        f"'{expression}'"
        ":s=44100"
        f":d={duration:.3f}"
    )


def _build_audio_filter(
    duration: float,
    rng: random.Random,
) -> str:
    """
    Build generated audio processing.

    The fade lengths are intentionally proportional to the Reel duration.
    """

    audio_source = _build_generated_audio(
        duration=duration,
        rng=rng,
    )

    fade_in = min(1.2, max(0.25, duration * 0.08))
    fade_out = min(1.8, max(0.4, duration * 0.12))

    fade_out_start = max(
        0.0,
        duration - fade_out,
    )

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
    """
    Render a unique 1080x1920 Reel from still images.

    Args:
        image_paths:
            One or more generated still images.

        cfg:
            Existing Config object.

        out_path:
            Output MP4 path.

        seed:
            Seed controlling visual/audio uniqueness.

    Returns:
        Path to the generated Reel.
    """

    if not ffmpeg_available():
        raise ReelError(
            "ffmpeg not found on PATH; cannot build a Reel"
        )

    imgs = _normalize_images(image_paths)

    if not imgs:
        raise ReelError(
            "no images supplied for the Reel"
        )

    # Validate images early.
    missing = [
        str(p)
        for p in imgs
        if not p.exists()
    ]

    if missing:
        raise ReelError(
            "image(s) not found: "
            + ", ".join(missing)
        )

    rc = cfg.reel

    out = Path(out_path)
    out.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    # ------------------------------------------------------------------
    # Unique seed
    # ------------------------------------------------------------------
    #
    # If seed=0, automatically create a different seed each invocation.
    #
    # If your workflow passes a deterministic seed, the same seed will
    # intentionally recreate the same Reel.
    # ------------------------------------------------------------------

    if seed == 0:
        seed = random.SystemRandom().randrange(
            1,
            2_147_483_647,
        )

    rng = random.Random(seed)

    # ------------------------------------------------------------------
    # Scene planning
    # ------------------------------------------------------------------

    scenes = _random_scene_plan(
        n=len(imgs),
        rc=rc,
        rng=rng,
    )

    # Calculate final duration after crossfades.
    total = sum(
        scene["duration"]
        for scene in scenes
    )

    for i in range(1, len(scenes)):
        previous = scenes[i - 1]["duration"]
        current = scenes[i]["duration"]

        crossfade = min(
            float(rc.crossfade_s),
            previous * 0.35,
            current * 0.35,
        )

        total -= crossfade

    total = max(1.0, total)

    # ------------------------------------------------------------------
    # Audio
    # ------------------------------------------------------------------

    audio = _pick_audio(
        rc.audio_dir,
        rng,
    )

    # ------------------------------------------------------------------
    # FFmpeg command
    # ------------------------------------------------------------------

    cmd: list[str] = [
        "ffmpeg",
        "-y",
        "-hide_banner",
        "-loglevel",
        "error",
    ]

    # Each image becomes an input stream.
    for idx, image in enumerate(imgs):
        duration = scenes[idx]["duration"]

        cmd += [
            "-loop",
            "1",
            "-t",
            f"{duration:.3f}",
            "-i",
            str(image),
        ]

    audio_idx = len(imgs)

    if audio is not None:
        # Loop external royalty-free track.
        cmd += [
            "-stream_loop",
            "-1",
            "-i",
            str(audio),
        ]
    else:
        # Generate unique audio directly inside FFmpeg.
        audio_filter = _build_audio_filter(
            duration=total,
            rng=rng,
        )

        cmd += [
            "-f",
            "lavfi",
            "-i",
            audio_filter,
        ]

    # ------------------------------------------------------------------
    # Video graph
    # ------------------------------------------------------------------

    filter_complex, video_label = _build_filtergraph(
        scenes=scenes,
        cfg=cfg,
    )

    cmd += [
        "-filter_complex",
        filter_complex,

        "-map",
        f"[{video_label}]",

        "-map",
        f"{audio_idx}:a",

        "-t",
        f"{total:.3f}",

        # --------------------------------------------------------------
        # Video
        # --------------------------------------------------------------

        "-c:v",
        "libx264",

        # Veryfast is suitable for GitHub Actions CPU.
        "-preset",
        "veryfast",

        # Good Reel quality without huge files.
        "-crf",
        "20",

        "-pix_fmt",
        "yuv420p",

        "-r",
        str(rc.fps),

        # Explicit dimensions in case config is changed.
        "-vf",
        f"scale={rc.width}:{rc.height}:"
        "force_original_aspect_ratio=disable",

        # --------------------------------------------------------------
        # Audio
        # --------------------------------------------------------------

        "-c:a",
        "aac",

        "-b:a",
        "128k",

        "-ar",
        "44100",

        "-ac",
        "2",

        # --------------------------------------------------------------
        # Instagram-friendly MP4
        # --------------------------------------------------------------

        "-movflags",
        "+faststart",

        "-shortest",

        str(out),
    ]

    # ------------------------------------------------------------------
    # Logging
    # ------------------------------------------------------------------

    log.info(
        "building unique reel: seed=%d scenes=%d duration=%.2fs "
        "resolution=%dx%d fps=%d audio=%s",
        seed,
        len(imgs),
        total,
        rc.width,
        rc.height,
        rc.fps,
        audio.name if audio else "generated-unique-ambient",
    )

    for i, scene in enumerate(scenes):
        log.info(
            "scene %d: duration=%.2fs motion=%s zoom=%.3f "
            "transition=%s effect=%s focal=(%.2f,%.2f)",
            i + 1,
            scene["duration"],
            scene["motion"],
            scene["zoom"],
            scene["transition"],
            scene["effect"],
            scene["focal_x"],
            scene["focal_y"],
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------

    try:
        subprocess.run(
            cmd,
            check=True,
            capture_output=True,
        )

    except subprocess.CalledProcessError as exc:
        detail = (
            exc.stderr.decode(
                "utf-8",
                "replace",
            )[-4000:]
            if exc.stderr
            else str(exc)
        )

        raise ReelError(
            "ffmpeg failed to assemble the Reel:\n"
            + detail
        ) from exc

    if not out.exists():
        raise ReelError(
            f"ffmpeg completed but output was not created: {out}"
        )

    if out.stat().st_size < 50_000:
        raise ReelError(
            f"generated Reel appears invalid or empty: {out}"
        )

    log.info(
        "reel successfully created: %s (%.2f MB)",
        out,
        out.stat().st_size / (1024 * 1024),
    )

    return out