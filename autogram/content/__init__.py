"""Pluggable content-type modules (separation of concern by "theme").

Each content type (photo, reel, carousel) is a small module that composes the
shared building blocks — scene/brief generation, image generation, safety gates,
post-processing and captioning — and returns a :class:`Deliverable` the
orchestrator publishes. New content types register themselves in ``REGISTRY``.
"""

from __future__ import annotations

# Importing the concrete modules registers them in REGISTRY (import side effect).
from . import carousel, photo, reel  # noqa: F401
from .base import (
    REGISTRY,
    ContentError,
    ContentType,
    Deliverable,
    ExitCode,
    ProductionContext,
    select_content_type,
)

__all__ = [
    "REGISTRY",
    "ContentError",
    "ContentType",
    "Deliverable",
    "ExitCode",
    "ProductionContext",
    "select_content_type",
]
