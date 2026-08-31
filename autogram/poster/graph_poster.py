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

import requests

from ..logging_utils import get_logger, register_secret
from .base import MediaArg, Poster, PosterError, PostResult, is_video_path, normalize_media
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

    def _create_container(
        self,
        media_url: str,
        caption: str,
        is_reel: bool = False,
        is_carousel_item: bool = False,
    ) -> str:
        data = {"access_token": self.access_token}
        if is_carousel_item:
            # A carousel child: image only, no caption (the parent carries it).
            data["image_url"] = media_url
            data["is_carousel_item"] = "true"
        elif is_reel:
            data["caption"] = caption
            data["media_type"] = "REELS"
            data["video_url"] = media_url
        else:
            data["caption"] = caption
            data["image_url"] = media_url
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            data=data,
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

    def _create_carousel_container(self, children: list[str], caption: str) -> str:
        resp = requests.post(
            f"{GRAPH_BASE}/{self.ig_user_id}/media",
            data={
                "media_type": "CAROUSEL",
                "children": ",".join(children),
                "caption": caption,
                "access_token": self.access_token,
            },
            timeout=60,
        )
        self._log_usage(resp)
        if resp.status_code != 200:
            raise PosterError(
                f"carousel container create failed: {resp.status_code} {resp.text[:300]}"
            )
        cid = resp.json().get("id")
        if not cid:
            raise PosterError("carousel container create returned no id")
        return str(cid)

    def _poll_container(self, container_id: str, timeout_s: float | None = None) -> None:
        deadline = time.monotonic() + (timeout_s or self.container_timeout_s)
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
    def publish(self, media: MediaArg, caption: str, alt_text: str) -> PostResult:
        # NOTE: alt_text is accepted for interface parity. The Graph publish
        # endpoint does not expose alt text; it is recorded in state but not
        # sent. One .mp4/.mov -> Reel (REELS, slower processing so a longer poll
        # budget); one image -> photo; many images -> CAROUSEL.
        paths = normalize_media(media)
        if not paths:
            raise PosterError("no media supplied to publish")
        is_reel = len(paths) == 1 and is_video_path(paths[0])
        is_carousel = len(paths) > 1
        kind = "reel" if is_reel else "carousel" if is_carousel else "image"

        if self.dry_run:
            log.info(
                "[dry-run] would host %d file(s) %s, then create a %s container -> poll -> "
                "POST /media_publish (caption <%d chars>)",
                len(paths),
                [str(p) for p in paths],
                kind,
                len(caption),
            )
            return PostResult(post_id="dry-run", url=None, backend=self.name, dry_run=True)

        media_url: str | None = None
        if is_carousel:
            children: list[str] = []
            for p in paths:
                child_url = self.image_host.upload(str(p))
                child_id = self._create_container(child_url, "", is_carousel_item=True)
                self._poll_container(child_id)
                children.append(child_id)
            container_id = self._create_carousel_container(children, caption)
            self._poll_container(container_id)
        else:
            media_url = self.image_host.upload(str(paths[0]))
            container_id = self._create_container(media_url, caption, is_reel=is_reel)
            self._poll_container(
                container_id, timeout_s=self.container_timeout_s * 3 if is_reel else None
            )

        media_id = self._publish_container(container_id)
        url = self._permalink(media_id)
        log.info("published %s id=%s url=%s", kind, media_id, url)
        extra = {"media_url": media_url} if media_url else {"children": str(len(paths))}
        return PostResult(post_id=media_id, url=url, backend=self.name, extra=extra)

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
