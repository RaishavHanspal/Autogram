from __future__ import annotations

import json

from autogram.state import State


def _record(sha, subject="s"):
    return {
        "image_sha256": sha,
        "brief": {"subject": subject},
        "status": "posted",
    }


def test_append_and_load(tmp_path):
    st = State(tmp_path / "history.json")
    assert st.load() == []
    st.append(_record("abc", "a nook"))
    st.append(_record("def", "a cliff"))
    data = st.load()
    assert len(data) == 2
    assert data[0]["image_sha256"] == "abc"


def test_idempotency_hash_lookup(tmp_path):
    st = State(tmp_path / "history.json")
    st.append(_record("hash1"))
    assert st.has_image_hash("hash1")
    assert not st.has_image_hash("nope")


def test_recent_subjects_and_briefs(tmp_path):
    st = State(tmp_path / "history.json")
    for i in range(5):
        st.append(_record(f"h{i}", f"subject {i}"))
    assert st.recent_subjects(3) == ["subject 2", "subject 3", "subject 4"]
    assert st.recent_briefs(2) == [{"subject": "subject 3"}, {"subject": "subject 4"}]


def test_atomic_write_no_partial_on_valid_json(tmp_path):
    path = tmp_path / "history.json"
    st = State(path)
    st.append(_record("x"))
    # File must always be valid JSON (atomic replace).
    parsed = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(parsed, list)
    # No temp files left behind.
    leftovers = list(tmp_path.glob(".history-*.tmp"))
    assert leftovers == []


def test_corrupt_history_treated_as_empty(tmp_path):
    path = tmp_path / "history.json"
    path.write_text("{not json", encoding="utf-8")
    st = State(path)
    assert st.load() == []
