"""Backend-agnostic posting interface."""

from __future__ import annotations

import abc
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


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
    """A publish backend. Implementations must honour dry_run."""

    name: str = "base"

    def __init__(self, dry_run: bool = False) -> None:
        self.dry_run = dry_run

    @abc.abstractmethod
    def publish(self, image_path: str | Path, caption: str, alt_text: str) -> PostResult:
        """Publish a single image with caption + alt text."""

    @abc.abstractmethod
    def comment(self, post_id: str, text: str) -> None:
        """Post a follow-up comment on a published post (e.g. first-comment tags)."""
