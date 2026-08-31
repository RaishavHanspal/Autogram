"""Rendering + external-media helpers.

This package owns everything that turns generated stills into deliverable media
and talks to external media services, kept separate from the creative "scene"
brain and the content-type modules:

  * reel.py       — CPU FFmpeg Reel renderer (still images -> 1080x1920 MP4) and
                    AI-clip assembler, including randomized music with a random
                    start offset.
  * ai_video.py   — optional AI image-to-video providers (PixVerse, HF).
  * image_host.py — temporary public image hosting (GitHub Release assets) for
                    providers that need a public URL.
"""

from __future__ import annotations
