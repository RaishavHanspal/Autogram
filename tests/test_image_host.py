"""GitHubReleaseHost: per-account asset names so two accounts never collide."""

from __future__ import annotations

from autogram.poster import image_host as ih


class _Resp:
    def __init__(self, status, json_data=None, text=""):
        self.status_code = status
        self._j = json_data or {}
        self.text = text

    def json(self):
        return self._j


def test_upload_asset_name_is_account_prefixed(tmp_path, monkeypatch):
    # Two accounts produce the same base filename in the same run; the upload
    # asset name must differ (parent dir = account id) or the 2nd account 422s.
    (tmp_path / "acctA").mkdir()
    (tmp_path / "acctB").mkdir()
    fa = tmp_path / "acctA" / "20260101T000000Z.jpg"
    fa.write_bytes(b"a" * 100)
    fb = tmp_path / "acctB" / "20260101T000000Z.jpg"
    fb.write_bytes(b"b" * 100)

    posted_names: list[str] = []

    def fake_get(url, **k):
        return _Resp(200, {"upload_url": "https://uploads/assets{?name}", "assets": []})

    def fake_post(url, **k):
        name = url.split("name=")[1]
        posted_names.append(name)
        return _Resp(201, {"browser_download_url": f"https://dl/{name}"})

    monkeypatch.setattr(ih.requests, "get", fake_get)
    monkeypatch.setattr(ih.requests, "post", fake_post)

    host = ih.GitHubReleaseHost("tok", "owner/repo")
    url_a = host.upload(fa)
    url_b = host.upload(fb)

    assert posted_names == ["acctA-20260101T000000Z.jpg", "acctB-20260101T000000Z.jpg"]
    assert url_a != url_b  # no collision


def test_upload_reuses_existing_asset_on_422(tmp_path, monkeypatch):
    f = tmp_path / "acct" / "x.jpg"
    f.parent.mkdir()
    f.write_bytes(b"x" * 100)

    def fake_get(url, **k):
        return _Resp(
            200,
            {
                "upload_url": "https://uploads/assets{?name}",
                "assets": [
                    {"name": "acct-x.jpg", "browser_download_url": "https://dl/acct-x.jpg"}
                ],
            },
        )

    def fake_post(url, **k):
        return _Resp(422, {}, text="already_exists")

    monkeypatch.setattr(ih.requests, "get", fake_get)
    monkeypatch.setattr(ih.requests, "post", fake_post)

    host = ih.GitHubReleaseHost("tok", "owner/repo")
    assert host.upload(f) == "https://dl/acct-x.jpg"
