"""Persistent run history: dedupe context, idempotency, and audit trail.

state/history.json holds one record per run. Writes are atomic (temp file +
os.replace) so a crash mid-write never corrupts the file. The history feeds:
  * recent-briefs context to the brief LLM (divergence),
  * near-duplicate rejection (subjects),
  * idempotency (never post the same image hash twice).
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any

from .logging_utils import get_logger

log = get_logger("state")


class State:
    def __init__(self, history_path: str | Path) -> None:
        self.path = Path(history_path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    def load(self) -> list[dict[str, Any]]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError) as exc:
            log.warning("history unreadable (%s); treating as empty", exc)
            return []
        if not isinstance(data, list):
            log.warning("history root is not a list; treating as empty")
            return []
        return data

    # ------------------------------------------------------------------ #
    def recent_records(self, n: int) -> list[dict[str, Any]]:
        return self.load()[-n:] if n > 0 else []

    def recent_briefs(self, n: int) -> list[dict[str, Any]]:
        return [r["brief"] for r in self.recent_records(n) if isinstance(r.get("brief"), dict)]

    def recent_subjects(self, n: int) -> list[str]:
        out: list[str] = []
        for r in self.recent_records(n):
            brief = r.get("brief")
            if isinstance(brief, dict) and brief.get("subject"):
                out.append(str(brief["subject"]))
        return out

    def has_image_hash(self, sha256: str) -> bool:
        return any(r.get("image_sha256") == sha256 for r in self.load())

    # ------------------------------------------------------------------ #
    def append(self, record: dict[str, Any]) -> None:
        """Append a record and write the whole file atomically."""
        history = self.load()
        history.append(record)
        self._atomic_write(history)
        log.info("history appended (%d records total)", len(history))

    def _atomic_write(self, history: list[dict[str, Any]]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(history, indent=2, ensure_ascii=False, sort_keys=False)
        fd, tmp = tempfile.mkstemp(dir=str(self.path.parent), prefix=".history-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            os.replace(tmp, self.path)
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)
