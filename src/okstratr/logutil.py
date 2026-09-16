"""Lightweight logging helpers for okstratr (stdlib only)."""

from __future__ import annotations

import logging
from typing import Any


def get_logger(name: str | None = None) -> logging.Logger:
    """Return a module logger; configures a basic stderr handler once."""
    logger = logging.getLogger(name or "okstratr")
    if not logging.getLogger("okstratr").handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
        root = logging.getLogger("okstratr")
        root.addHandler(handler)
        root.setLevel(logging.INFO)
        root.propagate = False
    return logger


def log_exception(logger: logging.Logger, msg: str, *args: Any) -> None:
    """Log an exception at ERROR with traceback (call from except blocks)."""
    logger.exception(msg, *args)


def log_warning(logger: logging.Logger, msg: str, *args: Any) -> None:
    logger.warning(msg, *args)
