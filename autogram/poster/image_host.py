"""Public image hosting for the Graph API (which needs a reachable image URL).

The default GitHubReleaseHost uploads the JPEG as an asset on a dated GitHub
Release using GITHUB_TOKEN and derives the public browser_download_url. It is
swappable: anything implementing ImageHost works.
"""

from __future__ import annotations

import abc
from pathlib import Path

import requests

from ..logging_utils import get_logger

log = get_logger("image_host")


class ImageHostError(RuntimeError):
    pass


class ImageHost(abc.ABC):
    @abc.abstractmethod
    def upload(self, image_path: str | Path) -> str:
        """Upload the image and return a publicly reachable URL."""


class GitHubReleaseHost(ImageHost):
    """Upload the JPEG as a release asset and return its public URL."""

    def __init__(self, token: str, repository: str, tag_prefix: str = "media") -> None:
        if not token or not repository:
            raise ImageHostError(
                "GitHubReleaseHost needs GITHUB_TOKEN and GITHUB_REPOSITORY "
                "(owner/repo). In Actions these are provided automatically."
            )
        self.token = token
        self.repository = repository  # owner/repo
        self.tag_prefix = tag_prefix
        self.api = "https://api.github.com"

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        }

    def _get_or_create_release(self, tag: str) -> dict:
        # Try to fetch an existing release by tag.
        r = requests.get(
            f"{self.api}/repos/{self.repository}/releases/tags/{tag}",
            headers=self._headers(),
            timeout=30,
        )
        if r.status_code == 200:
            return r.json()
        # Create it.
        r = requests.post(
            f"{self.api}/repos/{self.repository}/releases",
            headers=self._headers(),
            json={
                "tag_name": tag,
                "name": tag,
                "body": "autogram media assets (auto-generated).",
                "prerelease": True,
            },
            timeout=30,
        )
        if r.status_code not in (200, 201):
            raise ImageHostError(f"could not create release {tag}: {r.status_code} {r.text[:200]}")
        return r.json()

    def upload(self, image_path: str | Path) -> str:
        import mimetypes

        path = Path(image_path)
        tag = f"{self.tag_prefix}-{path.stem}"
        # Prefix the asset with the parent directory (the account id) so two
        # accounts posting in the same run never collide on an identical asset
        # name in the shared per-stamp release (which 422'd the second account).
        asset_name = f"{path.parent.name}-{path.name}"
        content_type = mimetypes.guess_type(path.name)[0] or "application/octet-stream"

        release = self._get_or_create_release(tag)
        upload_url = release["upload_url"].split("{")[0]

        r = requests.post(
            f"{upload_url}?name={asset_name}",
            headers={**self._headers(), "Content-Type": content_type},
            data=path.read_bytes(),
            timeout=300,
        )
        if r.status_code in (200, 201):
            url = r.json().get("browser_download_url")
            if not url:
                raise ImageHostError("upload succeeded but no browser_download_url returned")
            log.info("hosted media at %s", url)
            return url

        # 422 = an asset with this name already exists (e.g. a retry). Reuse it
        # instead of failing the post.
        if r.status_code == 422:
            fresh = self._get_or_create_release(tag)
            for asset in fresh.get("assets", []):
                if asset.get("name") == asset_name and asset.get("browser_download_url"):
                    log.info("reusing existing asset %s", asset_name)
                    return str(asset["browser_download_url"])
        raise ImageHostError(f"asset upload failed: {r.status_code} {r.text[:200]}")
