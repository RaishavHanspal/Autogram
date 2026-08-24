from __future__ import annotations

import pytest

pytest.importorskip("instagrapi")

from instagrapi.exceptions import ChallengeRequired, PleaseWaitFewMinutes  # noqa: E402

from autogram.poster.base import PosterError  # noqa: E402
from autogram.poster.instagrapi_poster import InstagrapiPoster  # noqa: E402


def test_instagrapi_dry_run_posts_nothing(tmp_path):
    poster = InstagrapiPoster(
        username="u",
        password="p",
        session_path=tmp_path / "sess.json",
        dry_run=True,
    )
    result = poster.publish("out/x.jpg", "caption", "alt")
    assert result.dry_run is True
    assert result.post_id == "dry-run"


def test_instagrapi_challenge_surfaces_actionable_error(tmp_path, monkeypatch):
    class _FakeClient:
        def login(self, username, password):
            raise ChallengeRequired()

    poster = InstagrapiPoster(
        username="u",
        password="p",
        session_path=tmp_path / "missing.json",
        dry_run=False,
    )
    monkeypatch.setattr(poster, "_build_client", lambda: _FakeClient())

    with pytest.raises(PosterError) as exc:
        poster.login()
    assert "challenge" in str(exc.value).lower()


def test_instagrapi_backoff_retries_then_succeeds(tmp_path, monkeypatch):
    monkeypatch.setattr("autogram.poster.instagrapi_poster.time.sleep", lambda s: None)
    poster = InstagrapiPoster("u", "p", session_path=tmp_path / "s.json", max_retries=3)

    state = {"n": 0}

    def _flaky():
        state["n"] += 1
        if state["n"] < 3:
            raise PleaseWaitFewMinutes()
        return "ok"

    assert poster._with_backoff(_flaky) == "ok"
    assert state["n"] == 3


def test_instagrapi_backoff_exhausts_and_raises(tmp_path, monkeypatch):
    monkeypatch.setattr("autogram.poster.instagrapi_poster.time.sleep", lambda s: None)
    poster = InstagrapiPoster("u", "p", session_path=tmp_path / "s.json", max_retries=2)

    def _always():
        raise PleaseWaitFewMinutes()

    with pytest.raises(PosterError):
        poster._with_backoff(_always)


def test_instagrapi_session_reuse(tmp_path, monkeypatch):
    # A live persisted session should be reused without a password login.
    (tmp_path / "s.json").write_text('{"uuids": {}}', encoding="utf-8")

    class _FakeClient:
        def __init__(self):
            self.logged_in = False

        def set_settings(self, s):
            pass

        def set_device(self, d):
            pass

        def set_user_agent(self, ua):
            pass

        def get_timeline_feed(self):
            return {"ok": True}

        def login(self, *a, **k):  # pragma: no cover - must not be called
            self.logged_in = True
            raise AssertionError("password login should not happen with live session")

    poster = InstagrapiPoster("u", "p", session_path=tmp_path / "s.json")
    monkeypatch.setattr(poster, "_build_client", lambda: _FakeClient())
    client = poster.login()
    assert client is not None
