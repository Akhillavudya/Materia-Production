"""Application logging configuration.

Provides a single `configure_logging()` entry point (called once at startup)
and a `get_logger()` helper so modules stop using bare `print()` for diagnostics.
"""

import logging
import os

_CONFIGURED = False


def configure_logging() -> None:
    """Initialise root logging once, honouring the LOG_LEVEL env var."""
    global _CONFIGURED
    if _CONFIGURED:
        return

    level = os.getenv("LOG_LEVEL", "INFO").upper()
    logging.basicConfig(
        level=getattr(logging, level, logging.INFO),
        format="%(asctime)s | %(levelname)-7s | %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    _CONFIGURED = True


def get_logger(name: str) -> logging.Logger:
    """Return a namespaced logger, ensuring logging is configured first."""
    configure_logging()
    return logging.getLogger(name)
