from __future__ import annotations

from pathlib import Path

import pytest

from autogram.poster import graph_poster
from autogram.poster.base import PosterError
from autogram.poster.graph_poster import GraphApiPoster


class _FakeResp:
    def __init__(self, status_code=200, json_data=None, headers=None, text=""):
        self.status_code = status_code
        self._json = json_data or {}
        self.headers = headers or {}
        self.text = text

    def json(self):
        return self._json


class _StubHost:
    def __init__(self, url="https://cdn.example/img.jpg"):
        self.url = url
        self.uploaded = None

    def upload(self, path):
        self.uploaded = path
        return self.url


def _install_fake_requests(monkeypatch, script):
    """script: list of _FakeResp returned in order across post+get calls."""
    calls = {"i": 0}

    def _next(*args, **kwargs):
        resp = script[calls["i"]]
        calls["i"] += 1
        return resp

    monkeypatch.setattr(graph_poster.requests, "post", _next)
    monkeypatch.setattr(graph_poster.requests, "get", _next)
    return calls


def test_graph_dry_run_posts_nothing():
    poster = GraphApiPoster(
        access_token=None, ig_user_id=None, image_host=_StubHost(), dry_run=True
    )
    result = poster.publish("out/x.jpg", "caption", "alt")
    assert result.dry_run is True
    assert result.post_id == "dry-run"


def test_graph_full_publish_flow(monkeypatch):
    host = _StubHost()
    _install_fake_requests(
        monkeypatch,
        [
            _FakeResp(200, {"id": "container123"}, {"x-app-usage": "call_count=1"}),  # create
            _FakeResp(200, {"status_code": "FINISHED"}),  # poll
            _FakeResp(200, {"id": "media999"}),  # publish
            _FakeResp(200, {"permalink": "https://instagram.com/p/abc/"}),  # permalink
        ],
    )
    poster = GraphApiPoster("token", "1789", host)
    result = poster.publish("out/x.jpg", "caption", "alt")
    assert result.post_id == "media999"
    assert result.url == "https://instagram.com/p/abc/"
    assert Path(host.uploaded) == Path("out/x.jpg")


def test_graph_carousel_flow(monkeypatch):
    host = _StubHost()
    _install_fake_requests(
        monkeypatch,
        [
            _FakeResp(200, {"id": "c1"}),  # child 1 create
            _FakeResp(200, {"status_code": "FINISHED"}),  # child 1 poll
            _FakeResp(200, {"id": "c2"}),  # child 2 create
            _FakeResp(200, {"status_code": "FINISHED"}),  # child 2 poll
            _FakeResp(200, {"id": "c3"}),  # child 3 create
            _FakeResp(200, {"status_code": "FINISHED"}),  # child 3 poll
            _FakeResp(200, {"id": "car"}),  # carousel container create
            _FakeResp(200, {"status_code": "FINISHED"}),  # carousel poll
            _FakeResp(200, {"id": "media_car"}),  # publish
            _FakeResp(200, {"permalink": "https://instagram.com/p/car/"}),  # permalink
        ],
    )
    poster = GraphApiPoster("token", "1789", host)
    result = poster.publish(["a.jpg", "b.jpg", "c.jpg"], "caption", "alt")
    assert result.post_id == "media_car"
    assert result.url == "https://instagram.com/p/car/"


def test_graph_container_error_raises(monkeypatch):
    _install_fake_requests(
        monkeypatch,
        [
            _FakeResp(200, {"id": "c1"}),
            _FakeResp(200, {"status_code": "ERROR"}),
        ],
    )
    poster = GraphApiPoster("token", "1789", _StubHost())
    with pytest.raises(PosterError):
        poster.publish("out/x.jpg", "caption", "alt")


def test_graph_create_failure_raises(monkeypatch):
    _install_fake_requests(monkeypatch, [_FakeResp(400, {}, {}, "bad request")])
    poster = GraphApiPoster("token", "1789", _StubHost())
    with pytest.raises(PosterError):
        poster.publish("out/x.jpg", "caption", "alt")


def test_graph_requires_creds_when_not_dry_run():
    with pytest.raises(PosterError):
        GraphApiPoster(access_token=None, ig_user_id=None, image_host=_StubHost(), dry_run=False)
