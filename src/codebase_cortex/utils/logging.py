"""Rich-based logging for Codebase Cortex."""

from __future__ import annotations

import logging
from pathlib import Path

from rich.console import Console
from rich.logging import RichHandler

console = Console()

# Module-level flag for verbose/debug mode
_verbose = False


def setup_logging(level: int = logging.INFO, verbose: bool = False) -> logging.Logger:
    """Configure and return the application logger."""
    global _verbose
    _verbose = verbose

    if verbose:
        level = logging.DEBUG

    handler = RichHandler(
        console=console,
        show_path=False,
        markup=True,
    )
    handler.setFormatter(logging.Formatter("%(message)s"))

    # Also log to .cortex/debug.log when verbose
    logger = logging.getLogger("cortex")
    logger.setLevel(level)

    # Remove existing handlers to avoid duplicates
    logger.handlers.clear()
    logger.addHandler(handler)

    if verbose:
        cortex_dir = Path.cwd() / ".cortex"
        if cortex_dir.exists():
            file_handler = logging.FileHandler(cortex_dir / "debug.log")
            file_handler.setLevel(logging.DEBUG)
            file_handler.setFormatter(
                logging.Formatter("%(asctime)s %(levelname)s %(message)s")
            )
            logger.addHandler(file_handler)

    return logger


def get_logger() -> logging.Logger:
    """Get the cortex logger, creating it if needed."""
    logger = logging.getLogger("cortex")
    if not logger.handlers:
        return setup_logging()
    return logger


def is_verbose() -> bool:
    return _verbose
