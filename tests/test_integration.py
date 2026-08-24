"""Opt-in integration test: a REAL end-to-end dry run.

Enabled only when AUTOGRAM_INTEGRATION=1. Requires the heavy deps (torch,
diffusers) and Ollama installed/reachable. It generates a real image, runs the
gates, and exercises the full pipeline in --dry-run (posts nothing).

    AUTOGRAM_INTEGRATION=1 pytest tests/test_integration.py -q
"""

from __future__ import annotations

import os

import pytest

INTEGRATION = os.environ.get("AUTOGRAM_INTEGRATION") == "1"

pytestmark = pytest.mark.skipif(
    not INTEGRATION, reason="set AUTOGRAM_INTEGRATION=1 to run the real dry-run"
)


def test_full_dry_run_produces_artifacts(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    # Minimal config with a fast turbo model.
    (tmp_path / "config").mkdir()
    (tmp_path / "config" / "config.yaml").write_text(
        "theme: a single ceramic mug on a wooden table\n"
        "image:\n  model: segmind/tiny-sd\n  steps: 1\n  width: 512\n  height: 512\n"
        "gates:\n  nsfw: false\n",
        encoding="utf-8",
    )
    from autogram.run import ExitCode, main

    code = main(["--dry-run", "--seed", "1234"])
    assert code == ExitCode.OK
    outputs = list((tmp_path / "out").glob("*.jpg"))
    assert outputs, "expected a generated JPEG"
