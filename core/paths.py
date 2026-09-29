"""Filesystem locations. Persistent data never lives in the PyInstaller extraction dir."""
from __future__ import annotations

import os
import sys
from pathlib import Path


def is_frozen() -> bool:
    return bool(getattr(sys, "frozen", False))


def bundle_dir() -> Path:
    """Read-only directory holding bundled assets (PyInstaller _MEIPASS or the source tree)."""
    if is_frozen() and hasattr(sys, "_MEIPASS"):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def data_dir() -> Path:
    """%APPDATA%\\ZeroPulse\\PRReviewAgent on Windows.

    ``ZEROPULSE_DATA_DIR`` overrides (used by tests and dev). On non-Windows hosts we use
    the XDG data directory so the code stays runnable for development.
    """
    override = os.environ.get("ZEROPULSE_DATA_DIR")
    if override:
        base = Path(override)
    elif sys.platform == "win32":
        appdata = os.environ.get("APPDATA") or str(Path.home() / "AppData" / "Roaming")
        base = Path(appdata) / "ZeroPulse" / "PRReviewAgent"
    else:
        xdg = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
        base = Path(xdg) / "ZeroPulse" / "PRReviewAgent"
    return base


def ensure_dirs() -> Path:
    base = data_dir()
    for sub in ("", "logs", "artifacts", "secrets"):
        (base / sub).mkdir(parents=True, exist_ok=True)
    return base


def config_path() -> Path:
    return data_dir() / "config.json"


def db_path() -> Path:
    return data_dir() / "reviews.db"


def logs_dir() -> Path:
    return data_dir() / "logs"


def artifacts_dir() -> Path:
    return data_dir() / "artifacts"


def secrets_dir() -> Path:
    return data_dir() / "secrets"


def assets_dir() -> Path:
    return bundle_dir() / "dashboard" / "assets"
