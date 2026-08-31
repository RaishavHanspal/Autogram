"""Backend-agnostic posting interface."""

from __future__ import annotations

import abc
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

# A deliverable is one or more media files. A single path (or 1-item list) is a
# photo/video post; a multi-image list is a carousel/album; a single .mp4 is a
# Reel/Short. Backends branch on count + suffix.
MediaArg = str | Path | Sequence[str | Path]

VIDEO_SUFFIXES = {".mp4", ".mov", ".webm"}


def normalize_media(media: MediaArg) -> list[Path]:
    """Coerce a single path or a sequence of paths into a list[Path]."""
    if isinstance(media, str | Path):
        return [Path(media)]
    return [Path(m) for m in media if m]


def is_video_path(path: str | Path) -> bool:
    return Path(path).suffix.lower() in VIDEO_SUFFIXES


@dataclass
class PostResult:
    post_id: str
    url: str | None = None
    backend: str = ""
    dry_run: bool = False
    extra: dict[str, Any] = field(default_factory=dict)


class PosterError(RuntimeError):
    """Base class for poster failures with an actionable message."""


class Poster(abc.ABC):
    """A publish backend. Implementations must honour dry_run.

    ``publish`` accepts either a single media path or a list of paths:
      * one image           -> a normal photo post;
      * one .mp4/.mov/.webm -> a Reel / Short;
      * many images         -> a carousel / album.
    Backends that cannot express a shape raise :class:`PosterError`.
    """

    name: str = "base"

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    @abc.abstractmethod
    def publish(self, media: MediaArg, caption: str, alt_text: str) -> PostResult:
        """Publish one or more media files with a caption + alt text."""

    @abc.abstractmethod
    def comment(self, post_id: str, text: str) -> None:
        """Post a follow-up comment on a published post (e.g. first-comment tags)."""
