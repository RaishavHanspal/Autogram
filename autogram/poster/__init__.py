"""Poster factory. Backend selected by POST_BACKEND (instagrapi | graph)."""

from __future__ import annotations

from ..config import Config, Secrets
from .base import Poster, PosterError, PostResult
from .graph_poster import GraphApiPoster
from .image_host import GitHubReleaseHost, ImageHost
from .instagrapi_poster import InstagrapiPoster
from .youtube_poster import YouTubePoster

__all__ = [
    "Poster",
    "PosterError",
    "PostResult",
    "GraphApiPoster",
    "InstagrapiPoster",
    "YouTubePoster",
    "ImageHost",
    "GitHubReleaseHost",
    "build_poster",
]


def build_poster(secrets: Secrets, cfg: Config, dry_run: bool = False) -> Poster:
    """Construct the configured backend. Switching backends needs no code change."""
    backend = (secrets.POST_BACKEND or "instagrapi").lower()
    if backend == "instagrapi":
        return InstagrapiPoster(
            username=secrets.IG_USERNAME,
            password=secrets.IG_PASSWORD,
            session_b64=secrets.IG_SESSION_B64,
            session_path=cfg.state.session_path,
            proxy=secrets.IG_PROXY,
            dry_run=dry_run,
        )
    if backend == "graph":
        # The image host is only needed for real posting; in dry-run we still
        # construct it lazily-safe (GitHubReleaseHost validates on use).
        host: ImageHost | None = None
        if secrets.GITHUB_TOKEN and secrets.GITHUB_REPOSITORY:
            host = GitHubReleaseHost(secrets.GITHUB_TOKEN, secrets.GITHUB_REPOSITORY)
        elif not dry_run:
            raise PosterError(
                "graph backend default image host needs GITHUB_TOKEN and "
                "GITHUB_REPOSITORY (owner/repo)"
            )
        else:
            host = _NullImageHost()
        return GraphApiPoster(
            access_token=secrets.IG_ACCESS_TOKEN,
            ig_user_id=secrets.IG_USER_ID,
            image_host=host,
            dry_run=dry_run,
        )
    if backend == "youtube":
        return YouTubePoster(
            client_id=secrets.YOUTUBE_CLIENT_ID,
            client_secret=secrets.YOUTUBE_CLIENT_SECRET,
            refresh_token=secrets.YOUTUBE_REFRESH_TOKEN,
            privacy_status=cfg.youtube.privacy_status,
            category_id=cfg.youtube.category_id,
            dry_run=dry_run,
        )
    raise PosterError(f"unknown POST_BACKEND: {backend!r} (expected instagrapi|graph|youtube)")


class _NullImageHost(ImageHost):
    """Placeholder host used only in graph dry-runs when no GH creds exist."""

    def upload(self, image_path: str) -> str:  # type: ignore[override]
        return "https://example.invalid/dry-run.jpg"
