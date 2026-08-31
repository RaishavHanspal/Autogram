"""Poster factory. One backend per account, chosen by the account's backend
(instagrapi | graph | youtube) with per-account credentials."""

from __future__ import annotations

from ..config import Config
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


def build_poster(
    backend: str,
    creds: dict[str, str | None],
    cfg: Config,
    dry_run: bool = False,
) -> Poster:
    """Construct a poster for one account from its resolved credentials.

    ``creds`` is a flat dict (ig_username, ig_password, ig_session_b64, ig_proxy,
    ig_access_token, ig_user_id, youtube_client_id/secret/refresh_token,
    github_token, github_repository) — see run.py's account-credential resolver.
    """
    backend = (backend or "instagrapi").lower()

    if backend == "instagrapi":
        return InstagrapiPoster(
            username=creds.get("ig_username"),
            password=creds.get("ig_password"),
            session_b64=creds.get("ig_session_b64"),
            session_path=cfg.state.session_path,
            proxy=creds.get("ig_proxy"),
            dry_run=dry_run,
        )

    if backend == "graph":
        # The image host is only needed for real posting; in dry-run we still
        # construct a safe placeholder.
        host: ImageHost
        token = creds.get("github_token")
        repo = creds.get("github_repository")
        if token and repo:
            host = GitHubReleaseHost(token, repo)
        elif not dry_run:
            raise PosterError(
                "graph backend default image host needs GITHUB_TOKEN and "
                "GITHUB_REPOSITORY (owner/repo)"
            )
        else:
            host = _NullImageHost()
        return GraphApiPoster(
            access_token=creds.get("ig_access_token"),
            ig_user_id=creds.get("ig_user_id"),
            image_host=host,
            dry_run=dry_run,
        )

    if backend == "youtube":
        return YouTubePoster(
            client_id=creds.get("youtube_client_id"),
            client_secret=creds.get("youtube_client_secret"),
            refresh_token=creds.get("youtube_refresh_token"),
            privacy_status=cfg.youtube.privacy_status,
            category_id=cfg.youtube.category_id,
            dry_run=dry_run,
        )

    raise PosterError(f"unknown backend: {backend!r} (expected instagrapi|graph|youtube)")


class _NullImageHost(ImageHost):
    """Placeholder host used only in graph dry-runs when no GH creds exist."""

    def upload(self, image_path: str) -> str:  # type: ignore[override]
        return "https://example.invalid/dry-run.jpg"
