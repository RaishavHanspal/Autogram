"""Reel audio selection: random track + random in-range start offset."""

from __future__ import annotations

import random

from autogram.render import reel as reel_mod


def _make_tracks(tmp_path, n=3):
    for i in range(n):
        (tmp_path / f"track{i}.mp3").write_bytes(b"\x00" * 1024)
    return tmp_path


def test_pick_audio_none_when_empty(tmp_path):
    assert reel_mod._pick_audio(str(tmp_path), random.Random(0), need_seconds=10) is None


def test_pick_audio_returns_in_range_offset(tmp_path, monkeypatch):
    _make_tracks(tmp_path)
    monkeypatch.setattr(reel_mod, "_media_duration", lambda p: 200.0)
    for seed in range(25):
        picked = reel_mod._pick_audio(str(tmp_path), random.Random(seed), need_seconds=10.0)
        assert picked is not None
        track, offset = picked
        assert track.suffix == ".mp3"
        # offset in [0, dur - need*0.5] = [0, 195]
        assert 0.0 <= offset <= 195.0
    # Across seeds the offset should actually vary (not always 0 / start).
    offsets = {
        reel_mod._pick_audio(str(tmp_path), random.Random(s), need_seconds=10.0)[1]
        for s in range(25)
    }
    assert len(offsets) > 1


def test_pick_audio_offset_zero_for_short_track(tmp_path, monkeypatch):
    _make_tracks(tmp_path)
    monkeypatch.setattr(reel_mod, "_media_duration", lambda p: 3.0)
    _track, offset = reel_mod._pick_audio(str(tmp_path), random.Random(1), need_seconds=12.0)
    assert offset == 0.0
