"""
Temporary public image hosting for external AI video APIs.

Uses GitHub Release assets when running inside GitHub Actions.

The generated URL is intended for temporary AI processing.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

from .logging_utils import get_logger

log = get_logger("image_host")


class ImageHostError(RuntimeError):
    """Image could not be made publicly reachable."""


def publish_image_to_github_release(
    image_path: str | Path,
    tag: str,
) -> str:
    """
    Upload an image to a GitHub Release and return its public URL.

    Requires:
      GITHUB_TOKEN
      GITHUB_REPOSITORY
      gh CLI
    """

    image = Path(image_path)

    if not image.exists():
        raise ImageHostError(f"image does not exist: {image}")

    token = os.getenv("GITHUB_TOKEN")
    repository = os.getenv("GITHUB_REPOSITORY")

    if not token or not repository:
        raise ImageHostError("GITHUB_TOKEN/GITHUB_REPOSITORY unavailable")

    env = {
        **os.environ,
        "GH_TOKEN": token,
    }

    # Create release if necessary.
    create = subprocess.run(
        [
            "gh",
            "release",
            "create",
            tag,
            "--repo",
            repository,
            "--title",
            f"Autogram temporary assets {tag}",
            "--notes",
            "Temporary Autogram Reel assets.",
        ],
        env=env,
        text=True,
        capture_output=True,
    )

    # Release already existing is fine.
    if create.returncode != 0 and "already_exists" not in (create.stderr or "").lower():
        log.warning(
            "release create returned %d: %s",
            create.returncode,
            create.stderr[-500:],
        )

    # Upload.
    upload = subprocess.run(
        [
            "gh",
            "release",
            "upload",
            tag,
            str(image),
            "--repo",
            repository,
            "--clobber",
        ],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    if upload.returncode != 0:
        raise ImageHostError("GitHub release upload failed: " + upload.stderr[-1000:])

    filename = image.name

    return f"https://github.com/{repository}" f"/releases/download/{tag}/" f"{filename}"