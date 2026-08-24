"""Official Instagram Graph API backend.

Requires an Instagram Business/Creator account linked to a Facebook Page, a
long-lived access token, and the numeric IG user id. The Graph API needs a
publicly reachable image URL, so an ImageHost provides one (default:
GitHubReleaseHost).

Publish is two steps: create a media container, poll it until FINISHED, then
publish the container.
"""

from __future__ import annotations

import time
from pathlib import Path

import requests

from ..logging_utils import get_logger, register_secret
from .base import Poster, PosterError, PostResult
from .image_host import ImageHost

log = get_logger("graph")

GRAPH_VERSION = "v19.0"
GRAPH_BASE = f"https://graph.facebook.com/{GRAPH_VERSION}"

# Instagram content publishing quota.
DAILY_POST_QUOTA = 25


class GraphApiPoster(Poster):
    name = "graph"

    def __init__(
        self,
        access_token: str | None,
        ig_user_id: str | None,
        image_host: ImageHost,
        dry_run: bool = False,
        container_timeout_s: int = 120,
    ) -> None:
        super().__init__(dry_run=dry_run)
        if not dry_run and (not access_token or not ig_user_id):
            raise PosterError("graph backend needs IG_ACCESS_TOKEN and IG_USER_ID")
        self.access_token = access_token
        self.ig_user_id = ig_user_id
        self.image_host = image_host
        self.container_timeout_s = container_timeout_s
        register_secret(access_token)

    # ------------------------------------------------------------------ #
    def _log_usage(self, resp: requests.Response) -> None:
        usage = resp.headers.get("x-app-usage") or resp.headers.get("X-App-Usage")
        if usage:
            log.info("graph x-app-usage: %s (daily publish quota: %d)", usage, DAILY_POST_QUOTA)

    def _create_container(self, image_url: str, caption: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            data={"image_url": image_url, "caption": caption, "access_token": self.access_token},
            timeout=60,
        )
        self._log_usage(resp)
        if resp.status_code != 200:
            raise PosterError(
                f"media container create failed: {resp.status_code} {resp.text[:300]}"
            )
        cid = resp.json().get("id")
        if not cid:
            raise PosterError("media container create returned no id")
        return str(cid)

    def _poll_container(self, container_id: str) -> None:
        deadline = time.monotonic() + self.container_timeout_s
        delay = 2.0
        while time.monotonic() < deadline:
            resp = requests.get(
                f"{GRAPH_BASE}/{container_id}",
                params={"fields": "status_code,status", "access_token": self.access_token},
                timeout=30,
            )
            if resp.status_code != 200:
                raise PosterError(
                    f"container status check failed: {resp.status_code} {resp.text[:200]}"
                )
            status = resp.json().get("status_code")
            log.info("container %s status=%s", container_id, status)
            if status == "FINISHED":
                return
            if status == "ERROR":
                raise PosterError(f"media container processing errored: {resp.json()}")
            time.sleep(delay)
            delay = min(delay * 1.5, 10.0)
        raise PosterError(f"container not FINISHED within {self.container_timeout_s}s")

    def _publish_container(self, container_id: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media_publish",
            data={"creation_id": container_id, "access_token": self.access_token},
            timeout=60,
        )
        self._log_usage(resp)
        if resp.status_code != 200:
            raise PosterError(f"media_publish failed: {resp.status_code} {resp.text[:300]}")
        media_id = resp.json().get("id")
        if not media_id:
            raise PosterError("media_publish returned no id")
        return str(media_id)

    def _permalink(self, media_id: str) -> str | None:
        try:
            resp = requests.get(
                f"{GRAPH_BASE}/{media_id}",
                params={"fields": "permalink", "access_token": self.access_token},
                timeout=30,
            )
            if resp.status_code == 200:
                return resp.json().get("permalink")
        except requests.RequestException:
            pass
        return None

    # ------------------------------------------------------------------ #
    def publish(self, image_path: str | Path, caption: str, alt_text: str) -> PostResult:
        # NOTE: alt_text is accepted for interface parity. The Graph publish
        # endpoint does not expose alt text on image posts; it is recorded in
        # state but not sent. Caption carries the visible text.
        if self.dry_run:
            log.info(
                "[dry-run] would host image %s, then POST /%s/media (image_url, caption "
                "<%d chars>) -> poll -> POST /media_publish",
                image_path,
                self.ig_user_id or "<user>",
                len(caption),
            )
            return PostResult(post_id="dry-run", url=None, backend=self.name, dry_run=True)

        image_url = self.image_host.upload(image_path)
        container_id = self._create_container(image_url, caption)
        self._poll_container(container_id)
        media_id = self._publish_container(container_id)
        url = self._permalink(media_id)
        log.info("published media id=%s url=%s", media_id, url)
        return PostResult(
            post_id=media_id, url=url, backend=self.name, extra={"image_url": image_url}
        )

    def comment(self, post_id: str, text: str) -> None:
        if self.dry_run:
            log.info("[dry-run] would POST /%s/comments (message <%d chars>)", post_id, len(text))
            return
        resp = requests.post(
            f"{GRAPH_BASE}/{post_id}/comments",
            data={"message": text, "access_token": self.access_token},
            timeout=60,
        )
        self._log_usage(resp)
        if resp.status_code != 200:
            raise PosterError(f"comment failed: {resp.status_code} {resp.text[:300]}")
        log.info("posted first comment on media %s", post_id)
