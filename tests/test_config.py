from __future__ import annotations

import pytest
from pydantic import ValidationError

from autogram.config import Config, PostprocConfig, load_config


def test_env_override(monkeypatch, tmp_path):
    cfg_file = tmp_path / "config.yaml"
    cfg_file.write_text("theme: base theme\nimage:\n  steps: 2\n", encoding="utf-8")
    monkeypatch.setenv("AUTOGRAM_IMAGE__STEPS", "4")
    monkeypatch.setenv("AUTOGRAM_THEME", "overridden")
    cfg = load_config(cfg_file)
    assert cfg.image.steps == 4
    assert cfg.theme == "overridden"


def test_defaults_when_no_file(tmp_path):
    cfg = load_config(tmp_path / "missing.yaml")
    assert isinstance(cfg, Config)
    assert cfg.image.model == "Lykon/dreamshaper-8"


def test_invalid_aspect_rejected():
    with pytest.raises(ValidationError):
        PostprocConfig(aspect="3:2")


def test_invalid_placement_rejected():
    from autogram.config import CaptionConfig

    with pytest.raises(ValidationError):
        CaptionConfig(hashtag_placement="banner")


def test_repo_config_loads():
    cfg = load_config("config/config.yaml")
    assert cfg.theme
    assert cfg.brief.axes  # axes present