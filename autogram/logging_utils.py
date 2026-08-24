"""Structured logging with secret redaction and per-stage timing.

The redaction filter scrubs any registered secret value from every log record
so a credential can never reach the logs, even if code accidentally logs it.
"""

from __future__ import annotations

import contextlib
import logging
import os
import re
import sys
import time
from collections.abc import Iterator

# Secrets registered here are masked in every log line.
_SECRETS: set[str] = set()
_MASK = "***REDACTED***"

# Patterns that look like credentials even if not explicitly registered.
_HEURISTIC_PATTERNS = [
    re.compile(r"(IG_PASSWORD|IG_ACCESS_TOKEN|IG_SESSION_B64|GITHUB_TOKEN)=\S+"),
    re.compile(r"(password|token|secret)\"?\s*[:=]\s*\"?[^\s\",]+", re.IGNORECASE),
]


def register_secret(value: str | None) -> None:
    """Register a secret value to be redacted from all future log output."""
    if value and len(value) >= 4:
        _SECRETS.add(value)


def register_env_secrets() -> None:
    """Register the known secret-bearing environment variables."""
    for key in (
        "IG_PASSWORD",
        "IG_ACCESS_TOKEN",
        "IG_SESSION_B64",
        "GITHUB_TOKEN",
        "IG_PROXY",
    ):
        register_secret(os.environ.get(key))


class RedactingFilter(logging.Filter):
    """Masks registered secret values and credential-shaped substrings."""

    def filter(self, record: logging.LogRecord) -> bool:
        try:
            msg = record.getMessage()
        except Exception:
            return True
        original = msg
        for secret in _SECRETS:
            if secret in msg:
                msg = msg.replace(secret, _MASK)
        for pat in _HEURISTIC_PATTERNS:
            msg = pat.sub(lambda m: m.group(0).split("=")[0] + "=" + _MASK, msg)
        if msg != original:
            # Overwrite so downstream formatters see the redacted text.
            record.msg = msg
            record.args = None
        return True


def setup_logging(level: str = "INFO") -> logging.Logger:
    """Configure the root autogram logger. Idempotent."""
    register_env_secrets()
    logger = logging.getLogger("autogram")
    logger.setLevel(level.upper())
    logger.propagate = False
    if logger.handlers:
        return logger
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(
        logging.Formatter(
            fmt="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
            datefmt="%Y-%m-%dT%H:%M:%S",
        )
    )
    handler.addFilter(RedactingFilter())
    logger.addHandler(handler)
    return logger


def get_logger(name: str = "autogram") -> logging.Logger:
    return logging.getLogger(name if name.startswith("autogram") else f"autogram.{name}")


@contextlib.contextmanager
def stage_timer(logger: logging.Logger, stage: str) -> Iterator[None]:
    """Log the wall-clock cost of a pipeline stage."""
    start = time.perf_counter()
    logger.info("stage.start %s", stage)
    try:
        yield
    finally:
        elapsed = time.perf_counter() - start
        logger.info("stage.done  %s (%.1fs)", stage, elapsed)
