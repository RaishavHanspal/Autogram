"""instagrapi backend (Instagram private API, MIT).

WARNING: instagrapi uses Instagram's private API, which violates Instagram's
Terms of Service. Use a dedicated account, keep volume low (1-2/day), and
prefer the Graph backend for anything that matters. See the README.

Session persistence is mandatory here: a fresh password login every run is the
single biggest cause of challenges and bans. We reload settings from
IG_SESSION_B64 (or a session file) and fall back to password login only when
the session is dead.
"""

from __future__ import annotations

import base64
import json
import random
import time
from pathlib import Path
from typing import Any

from ..logging_utils import get_logger, register_secret
from .base import Poster, PosterError, PostResult

log = get_logger("instagrapi")

# Pinned device + user agent so the fingerprint stays stable across runs.
PINNED_DEVICE: dict[str, Any] = {
    "app_version": "269.0.0.18.75",
    "android_version": 26,
    "android_release": "8.0.0",
    "dpi": "480dpi",
    "resolution": "1080x1920",
    "manufacturer": "OnePlus",
    "device": "devitron",
    "model": "6T Dev",
    "cpu": "qcom",
    "version_code": "314665256",
}
PINNED_USER_AGENT = (
    "Instagram 269.0.0.18.75 Android "
    "(26/8.0.0; 480dpi; 1080x1920; OnePlus; 6T Dev; devitron; qcom; en_US; 314665256)"
)


class InstagrapiPoster(Poster):
    name = "instagrapi"

    def __init__(
        self,
        username: str | None,
        password: str | None,
        session_b64: str | None = None,
        session_path: str | Path = "state/ig_session.json",
        proxy: str | None = None,
        dry_run: bool = False,
        max_retries: int = 3,
    ) -> None:
        super().__init__(dry_run=dry_run)
        self.username = username
        self.password = password
        self.session_b64 = session_b64
        self.session_path = Path(session_path)
        self.proxy = proxy
        self.max_retries = max_retries
        register_secret(password)
        register_secret(session_b64)
        register_secret(proxy)
        self._client: Any = None

    # ------------------------------------------------------------------ #
    def _build_client(self) -> Any:
        from instagrapi import Client

        client = Client()
        client.set_device(PINNED_DEVICE)
        client.set_user_agent(PINNED_USER_AGENT)
        if self.proxy:
            client.set_proxy(self.proxy)
        return client

    def _load_settings(self) -> dict | None:
        if self.session_b64:
            try:
                return json.loads(base64.b64decode(self.session_b64).decode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("IG_SESSION_B64 could not be decoded (%s); ignoring", exc)
        if self.session_path.exists():
            try:
                return json.loads(self.session_path.read_text(encoding="utf-8"))
            except Exception as exc:  # noqa: BLE001
                log.warning("session file unreadable (%s); ignoring", exc)
        return None

    def _persist_settings(self, client: Any) -> None:
        settings = client.get_settings()
        self.session_path.parent.mkdir(parents=True, exist_ok=True)
        self.session_path.write_text(json.dumps(settings), encoding="utf-8")
        b64 = base64.b64encode(json.dumps(settings).encode("utf-8")).decode("ascii")
        register_secret(b64)
        log.info(
            "session persisted to %s. To seed CI, run: "
            "gh secret set IG_SESSION_B64 --body <base64> "
            "(base64 written to session file; do NOT log it).",
            self.session_path,
        )

    def login(self) -> Any:
        if self._client is not None:
            return self._client
        from instagrapi.exceptions import (
            ChallengeRequired,
            LoginRequired,
            TwoFactorRequired,
        )

        client = self._build_client()
        settings = self._load_settings()

        if settings:
            log.info("reusing persisted session")
            client.set_settings(settings)
            # Re-pin device/UA in case the stored settings differ.
            client.set_device(PINNED_DEVICE)
            client.set_user_agent(PINNED_USER_AGENT)
            try:
                client.get_timeline_feed()  # cheap liveness probe
                self._client = client
                return client
            except LoginRequired:
                log.warning("persisted session is dead; falling back to password login")

        if not self.username or not self.password:
            raise PosterError(
                "no valid session and IG_USERNAME/IG_PASSWORD not set — cannot log in"
            )

        try:
            client.login(self.username, self.password)
        except TwoFactorRequired as exc:
            raise PosterError(
                "Two-factor auth required. Log in locally once to create a session, "
                "then seed IG_SESSION_B64 (see README)."
            ) from exc
        except ChallengeRequired as exc:
            raise PosterError(
                "Instagram issued a challenge (verify it's you). Complete it in the "
                "app/website from the same IP, then re-seed IG_SESSION_B64. Avoid "
                "frequent fresh password logins."
            ) from exc

        self._persist_settings(client)
        self._client = client
        return client

    # ------------------------------------------------------------------ #
    def _with_backoff(self, func: Any, *args: Any, **kwargs: Any) -> Any:
        from instagrapi.exceptions import PleaseWaitFewMinutes

        last: Exception | None = None
        for attempt in range(1, self.max_retries + 1):
            try:
                return func(*args, **kwargs)
            except PleaseWaitFewMinutes as exc:
                last = exc
                sleep = min(300, 2**attempt * 10) + random.uniform(0, 15)
                log.warning(
                    "rate limited (PleaseWaitFewMinutes); attempt %d/%d, sleeping %.0fs",
                    attempt,
                    self.max_retries,
                    sleep,
                )
                time.sleep(sleep)
        raise PosterError(f"still rate-limited after {self.max_retries} attempts") from last

    # ------------------------------------------------------------------ #
    def publish(self, image_path: str | Path, caption: str, alt_text: str) -> PostResult:
        image_path = str(image_path)
        if self.dry_run:
            log.info(
                "[dry-run] would client.photo_upload(path=%s, caption=<%d chars>, "
                "extra_data={'custom_accessibility_caption': <alt %d chars>})",
                image_path,
                len(caption),
                len(alt_text),
            )
            return PostResult(post_id="dry-run", url=None, backend=self.name, dry_run=True)

        client = self.login()
        extra_data = {"custom_accessibility_caption": alt_text} if alt_text else {}

        def _do() -> Any:
            return client.photo_upload(image_path, caption=caption, extra_data=extra_data)

        media = self._with_backoff(_do)
        code = getattr(media, "code", None)
        url = f"https://www.instagram.com/p/{code}/" if code else None
        pk = str(getattr(media, "pk", "") or getattr(media, "id", ""))
        log.info("published media pk=%s url=%s", pk, url)
        return PostResult(post_id=pk, url=url, backend=self.name)

    def comment(self, post_id: str, text: str) -> None:
        if self.dry_run:
            log.info(
                "[dry-run] would client.media_comment(pk=%s, text=<%d chars>)", post_id, len(text)
            )
            return
        client = self.login()
        self._with_backoff(client.media_comment, post_id, text)
        log.info("posted first comment on pk=%s", post_id)
