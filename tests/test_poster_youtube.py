from __future__ import annotations

import pytest

from autogram.poster.base import PosterError
from autogram.poster.youtube_poster import YouTubePoster


class _Response:
    def __init__(self, status_code=200, payload=None, headers=None, text=""):
        self.status_code = status_code
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._payload


def test_youtube_dry_run_needs_no_credentials():
    result = YouTubePoster(None, None, None, dry_run=True).publish(
        "out/short.mp4", "caption", "alt"
    )
    assert result.dry_run is True
    assert result.backend == "youtube"


def test_youtube_rejects_still_image(tmp_path):
    image = tmp_path / "still.jpg"
    image.write_bytes(b"x")
    poster = YouTubePoster("id", "secret", "refresh")
    with pytest.raises(PosterError, match="rendered video"):
        poster.publish(image, "caption", "alt")


def test_youtube_resumable_upload(monkeypatch, tmp_path):
    video = tmp_path / "short.mp4"
    video.write_bytes(b"video")
    responses = iter(
        [
            _Response(payload={"access_token": "token"}),
            _Response(headers={"Location": "https://upload.example/session"}),
            _Response(payload={"id": "video123"}),
        ]
    )

    monkeypatch.setattr(
        "autogram.poster.youtube_poster.requests.post", lambda *a, **k: next(responses)
    )
    monkeypatch.setattr(
        "autogram.poster.youtube_poster.requests.put", lambda *a, **k: next(responses)
    )

    result = YouTubePoster("id", "secret", "refresh", privacy_status="unlisted").publish(
        video, "Useful Short\n#ai", "An accessible description"
    )
    assert result.post_id == "video123"
    assert result.url == "https://www.youtube.com/watch?v=video123"
