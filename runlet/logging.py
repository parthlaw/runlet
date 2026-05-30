"""Public helper for configuring runlet logging in scripts and CLIs."""

from __future__ import annotations

import logging


def setup_logging(level: str = "INFO") -> None:
    """Configure root logger. Call this before ``build_runner`` in scripts."""
    logging.basicConfig(
        level=getattr(logging, level.upper()),
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
