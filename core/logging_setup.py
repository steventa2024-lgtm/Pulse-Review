"""Rotating file logging with credential redaction."""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import paths
from .security import SecretRedactingFilter

_CONFIGURED = False


def setup_logging(level: int = logging.INFO, console: bool | None = None) -> None:
    global _CONFIGURED
    if _CONFIGURED:
        return
    paths.ensure_dirs()
    root = logging.getLogger()
    root.setLevel(level)
    redactor = SecretRedactingFilter()
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    fh = logging.handlers.RotatingFileHandler(
        paths.logs_dir() / "app.log", maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setFormatter(fmt)
    fh.addFilter(redactor)
    root.addHandler(fh)
    if console is None:
        console = sys.stderr is not None and not getattr(sys, "frozen", False)
    if console:
        ch = logging.StreamHandler(sys.stderr)
        ch.setFormatter(fmt)
        ch.addFilter(redactor)
        root.addHandler(ch)
    for noisy in ("httpx", "httpcore", "urllib3", "openai"):
        logging.getLogger(noisy).setLevel(logging.WARNING)
    _CONFIGURED = True
