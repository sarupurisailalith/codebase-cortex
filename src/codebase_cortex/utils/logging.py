"""Rich-based logging for Codebase Cortex."""

from __future__ import annotations

import logging

from rich.console import Console
from rich.logging import RichHandler

console = Console()


def setup_logging(level: int = logging.INFO) -> logging.Logger:
    """Configure and return the application logger."""
    handler = RichHandler(
        console=console,
        show_path=False,
        markup=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    logger = logging.getLogger("cortex")
    logger.setLevel(level)
    logger.addHandler(handler)
    return logger


def get_logger() -> logging.Logger:
    """Get the cortex logger, creating it if needed."""
    logger = logging.getLogger("cortex")
    if not logger.handlers:
        return setup_logging()
    return logger
