from __future__ import annotations

from autogram.scene import (
    Brief,
    compute_seed,
    generate_brief,
    is_near_duplicate,
    render_prompts,
    select_axis_hints,
)


def test_compute_seed_is_deterministic():
    a = compute_seed("2026-08-23", "salt")
    b = compute_seed("2026-08-23", "salt")
    c = compute_seed("2026-08-24", "salt")
    assert a == b
    assert a != c
    assert 0 <= a < 2**32


def test_near_duplicate_detection():
    history = ["a cozy reading nook by a bright window"]
    assert is_near_duplicate("a cozy reading nook by a window that is bright", history, 85)
    assert not is_near_duplicate("a busy street market at night", history, 85)


def test_select_axis_hints_reproducible():
    import random

    axes = {"season": ["spring", "summer", "autumn", "winter"], "focal_length": ["35mm", "85mm"]}
    h1 = select_axis_hints(random.Random(42), axes)
    h2 = select_axis_hints(random.Random(42), axes)
    assert h1 == h2
    assert set(h1) == {"season", "focal_length"}


def test_render_prompts_no_double_commas(cfg, brief):
    pos, neg = render_prompts(brief, cfg)
    assert ", ," not in pos
    assert "35mm, photographic" in pos
    assert neg == cfg.image.negative_template


class _FakeOllama:
    def __init__(self, replies):
        self._replies = list(replies)
        self.calls = 0

    def chat_json(self, model, messages, seed, temperature):
        self.calls += 1
        return self._replies.pop(0)


def _brief_dict(subject):
    return {
        "subject": subject,
        "setting": "s",
        "lighting": "l",
        "mood": "m",
        "composition": "c",
        "color_palette": "p",
        "time_of_day": "t",
        "style_modifiers": ["x"],
    }


def test_generate_brief_rejects_duplicate_then_accepts(cfg, brief):
    history = ["a cozy reading nook by a bright window"]
    client = _FakeOllama(
        [
            _brief_dict("a cozy reading nook by a window that is bright"),  # near-dup
            _brief_dict("a rugged coastal cliff at dawn"),  # unique
        ]
    )
    out = generate_brief(
        client=client,
        cfg=cfg,
        seed=7,
        run_date="2026-08-23",
        history_subjects=history,
        recent_briefs=[],
        model="m",
    )
    assert isinstance(out, Brief)
    assert out.subject == "a rugged coastal cliff at dawn"
    assert client.calls == 2


def test_generate_brief_falls_back_when_all_invalid(cfg):
    class _AlwaysBad:
        def chat_json(self, **kwargs):
            return {"not": "a valid brief"}

    out = generate_brief(
        client=_AlwaysBad(),
        cfg=cfg,
        seed=1,
        run_date="2026-08-23",
        history_subjects=[],
        recent_briefs=[],
        model="m",
    )
    assert isinstance(out, Brief)  # deterministic fallback, run never dies
