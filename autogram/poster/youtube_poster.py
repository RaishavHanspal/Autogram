"""Official YouTube Data API backend for uploading rendered Shorts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import requests

from ..logging_utils import register_secret
from .base import Poster, PosterError, PostResult

_TOKEN_URL = "https://oauth2.googleapis.com/token"
_UPLOAD_URL = "https://www.googleapis.com/upload/youtube/v3/videos"


class YouTubePoster(Poster):
    """Upload an MP4 to the authenticated channel using a refresh token."""

    name = "youtube"

    def __init__(
        self,
        client_id: str | None,
        client_secret: str | None,
        refresh_token: str | None,
        privacy_status: str = "private",
        category_id: str = "22",
        dry_run: bool = False,
    ) -> None:
        super().__init__(dry_run=dry_run)
        if privacy_status not in {"private", "unlisted", "public"}:
            raise PosterError("youtube privacy_status must be private, unlisted, or public")
        if not dry_run and (not client_id or not client_secret or not refresh_token):
            raise PosterError(
                "youtube backend needs YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET, "
                "and YOUTUBE_REFRESH_TOKEN"
            )
        self.client_id = client_id
        self.client_secret = client_secret
        self.refresh_token = refresh_token
        self.privacy_status = privacy_status
        self.category_id = category_id
        register_secret(client_secret)
        register_secret(refresh_token)

    def _access_token(self) -> str:
        response = requests.post(
            _TOKEN_URL,
            data={
                "client_id": self.client_id,
                "client_secret": self.client_secret,
                "refresh_token": self.refresh_token,
                "grant_type": "refresh_token",
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise PosterError(f"YouTube OAuth refresh failed: {response.status_code} {response.text[:300]}")
        token = response.json().get("access_token")
        if not token:
            raise PosterError("YouTube OAuth refresh returned no access_token")
        return str(token)

    @staticmethod
    def _metadata(caption: str, alt_text: str, privacy_status: str, category_id: str) -> dict[str, Any]:
        title = next((line.strip() for line in caption.splitlines() if line.strip()), "Autogram Short")
        title = title[:100]
        description = caption[:5000]
        if alt_text.strip():
            description = f"{description}\n\n{alt_text.strip()}"[:5000]
        return {
            "snippet": {"title": title, "description": description, "categoryId": category_id},
            "status": {"privacyStatus": privacy_status, "selfDeclaredMadeForKids": False},
        }

    def publish(self, image_path: str | Path, caption: str, alt_text: str) -> PostResult:
        video_path = Path(image_path)
        if self.dry_run:
            return PostResult(post_id="dry-run", backend=self.name, dry_run=True)
        if not video_path.is_file():
            raise PosterError(f"YouTube upload file not found: {video_path}")
        if video_path.suffix.lower() not in {".mp4", ".mov", ".webm"}:
            raise PosterError("YouTube Shorts requires a rendered video (MP4 recommended); enable reel.enabled")

        token = self._access_token()
        metadata = self._metadata(caption, alt_text, self.privacy_status, self.category_id)
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json; charset=UTF-8",
            "X-Upload-Content-Length": str(video_path.stat().st_size),
            "X-Upload-Content-Type": "video/mp4",
        }
        session = requests.post(
            _UPLOAD_URL,
            params={"uploadType": "resumable", "part": "snippet,status"},
            headers=headers,
            data=json.dumps(metadata),
            timeout=30,
        )
        if session.status_code not in {200, 201}:
            raise PosterError(f"YouTube upload session failed: {session.status_code} {session.text[:300]}")
        upload_url = session.headers.get("Location")
        if not upload_url:
            raise PosterError("YouTube upload session returned no Location header")

        with video_path.open("rb") as stream:
            uploaded = requests.put(
                upload_url,
                headers={"Content-Type": "video/mp4", "Content-Length": str(video_path.stat().st_size)},
                data=stream,
                timeout=900,
            )
        if uploaded.status_code not in {200, 201}:
            raise PosterError(f"YouTube upload failed: {uploaded.status_code} {uploaded.text[:300]}")
        video_id = uploaded.json().get("id")
        if not video_id:
            raise PosterError("YouTube upload returned no video id")
        return PostResult(
            post_id=str(video_id),
            url=f"https://www.youtube.com/watch?v={video_id}",
            backend=self.name,
        )

    def comment(self, post_id: str, text: str) -> None:
        # Hashtags stay in the description; this backend deliberately avoids a
        # second write API call for comments.
        return None