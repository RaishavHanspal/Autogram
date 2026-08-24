from __future__ import annotations

import pytest

from autogram.caption import (
    _RawHashtag,
    compose_final_caption,
    enforce_caption_rules,
    generate_caption,
    load_banned_hashtags,
    normalize_tag,
    process_hashtags,
    validate_tier_distribution,
)


def test_normalize_tag():
    assert normalize_tag("#Design") == "#Design"
    assert normalize_tag("design") == "#design"
    assert normalize_tag("  scandi  ") == "#scandi"
    assert normalize_tag("#a") is None  # too short
    assert normalize_tag("#has space") is None
    assert normalize_tag("#bad-dash") is None
    assert normalize_tag("#" + "x" * 40) is None  # too long


def test_process_hashtags_dedupe_filter_and_brand(cfg):
    banned = {"alone"}
    raw = [
        _RawHashtag(tag="design", tier="broad"),
        _RawHashtag(tag="#Design", tier="mid"),  # dup of design (case-insensitive)
        _RawHashtag(tag="alone", tier="mid"),  # banned
        _RawHashtag(tag="scandi", tier="niche"),
    ]
    tags = process_hashtags(raw, cfg, banned)
    lowered = [t.lower() for t in tags]
    assert "#design" in lowered
    assert lowered.count("#design") == 1
    assert "#alone" not in lowered
    # brand tags appended
    assert "#autogram" in lowered
    assert "#slowdesign" in lowered
    # hard cap to max_count
    assert len(tags) <= cfg.hashtags.max_count


def test_hashtag_hard_cap_30(cfg):
    cfg.hashtags.max_count = 100
    raw = [_RawHashtag(tag=f"tag{i}", tier="mid") for i in range(50)]
    tags = process_hashtags(raw, cfg, set())
    assert len(tags) <= 30


def test_validate_tier_distribution():
    raw = (
        [_RawHashtag(tag=f"b{i}", tier="broad") for i in range(3)]
        + [_RawHashtag(tag=f"m{i}", tier="mid") for i in range(5)]
        + [_RawHashtag(tag=f"n{i}", tier="niche") for i in range(2)]
    )

    class _C:
        class hashtags:
            tier_broad = 0.30
            tier_mid = 0.50
            tier_niche = 0.20

    assert validate_tier_distribution(raw, _C) is True


def test_enforce_caption_rules_emoji_budget(cfg):
    cfg.caption.emoji_budget = 1
    out = enforce_caption_rules("Morning light 🌞 warms the room 🌿 gently ✨", cfg)
    emoji = [c for c in out if ord(c) > 0x2600]
    assert len(emoji) <= 1


def test_enforce_caption_rules_strips_mentions(cfg):
    out = enforce_caption_rules("Love this @randomaccount vibe", cfg)
    assert "@randomaccount" not in out


def test_compose_final_caption_length_enforced(cfg):
    cfg.caption.max_length = 50
    with pytest.raises(ValueError):
        compose_final_caption("x" * 60, ["#a", "#b"], cfg)


def test_compose_final_caption_placement(cfg):
    cfg.caption.hashtag_placement = "caption"
    out = compose_final_caption("hello", ["#a", "#b"], cfg)
    assert "#a #b" in out


def test_generate_caption_uses_fallback_on_failure(cfg, brief):
    from autogram.caption import OllamaError

    class _AlwaysBad:
        def chat_json(self, **kwargs):
            raise OllamaError("boom")

    result = generate_caption(_AlwaysBad(), brief, cfg, seed=1, model="m", banned=set())
    assert result.caption  # never empty
    assert result.alt_text


def test_generate_caption_happy_path(cfg, brief):
    class _Good:
        def chat_json(self, **kwargs):
            return {
                "caption": "A quiet corner to begin the day.\nWhere light lingers.",
                "hashtags": [
                    {"tag": "scandinavian", "tier": "broad"},
                    {"tag": "interiordesign", "tier": "mid"},
                    {"tag": "slowliving", "tier": "niche"},
                    {"tag": "morninglight", "tier": "mid"},
                ],
                "alt_text": "A reading nook by a window in soft morning light.",
            }

    result = generate_caption(_Good(), brief, cfg, seed=1, model="m", banned=set())
    assert result.caption.startswith("A quiet corner")
    assert len(result.hashtags) >= cfg.hashtags.min_count
    assert result.alt_text


def test_load_banned_hashtags_reads_file():
    banned = load_banned_hashtags("config/banned_hashtags.txt")
    assert "alone" in banned
    assert "tagsforlikes" in banned
