"""autogram — free, open-source, self-hosted Instagram auto-poster.

Pipeline: theme -> brief -> image -> post-process -> caption -> safety -> post.
Each stage lives in its own module behind a small interface so stages can be
swapped without touching the others. See autogram/run.py for orchestration.
"""

__version__ = "0.1.0"
