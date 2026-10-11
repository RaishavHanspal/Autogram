"""Random theme prompts: word budget, subject kept, and per-run variety."""

from __future__ import annotations

import random

from autogram.random_theme import (
    assemble_prompt,
    build_random_prompt,
    new_rng,
    pick_parts,
)

POOLS = {
    "subject": ["a potter shaping a clay bowl", "a cyclist on a stone bridge"],
    "setting": ["a misty valley", "a harbor village at dusk"],
    "lighting": ["soft window light", "blue-hour ambience"],
    "lens": ["35mm lens", "85mm portrait lens"],
    "mood": ["quiet and contemplative", "playful"],
    "composition": ["rule-of-thirds framing"],
    "palette": ["muted earth tones"],
}
SUFFIX = "photorealistic, natural colors, sharp focus, detailed, 8k"


def test_prompt_respects_word_budget():
    rng = random.Random(0)
    for _ in range(300):
        prompt, _ = build_random_prompt(POOLS, rng, quality_suffix=SUFFIX, max_words=40)
        assert len(prompt.split()) <= 40, prompt


def test_tight_budget_keeps_subject_and_drops_low_priority_parts():
    parts = {"subject": "a potter shaping a clay bowl", "setting": "a misty valley",
             "palette": "muted earth tones"}
    prompt = assemble_prompt(parts, SUFFIX, max_words=14)
    assert len(prompt.split()) <= 14
    assert "potter" in prompt          # subject survives
    assert "muted earth tones" not in prompt  # lowest priority dropped first


def test_quality_suffix_kept_when_budget_allows():
    prompt = assemble_prompt(pick_parts(POOLS, random.Random(1)), SUFFIX, max_words=40)
    assert prompt.endswith(SUFFIX)


def test_runs_differ():
    seen = {build_random_prompt(POOLS, new_rng(), quality_suffix=SUFFIX, max_words=40)[0]
            for _ in range(60)}
    assert len(seen) > 5


def test_recent_subjects_are_avoided_when_possible():
    recent = ["a potter shaping a clay bowl"]
    for seed in range(50):
        _, parts = build_random_prompt(POOLS, random.Random(seed), quality_suffix=SUFFIX,
                                       max_words=40, recent_subjects=recent)
        assert parts["subject"] != recent[0]
