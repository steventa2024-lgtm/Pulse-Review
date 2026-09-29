"""ZeroPulse PR Review Agent — desktop entry point.  Run from source with:  python main.py"""
from __future__ import annotations

import multiprocessing
import os
import socket
import sys


def _ensure_std_streams() -> None:
    """Windowed PyInstaller builds have no console: stdout/stderr are None, which breaks uvicorn logging."""
    for name in ("stdout", "stderr"):
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))


def _find_free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def webview2_available() -> bool:
    """True when the Microsoft Edge WebView2 runtime (needed for the native window) is installed."""
    if sys.platform != "win32":
        return True
    try:
        import winreg
    except ImportError:
        return False
    keys = [
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
        (winreg.HKEY_CURRENT_USER, r"Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"),
    ]
    for hive, path in keys:
        try:
            with winreg.OpenKey(hive, path) as k:
                if winreg.QueryValueEx(k, "pv")[0] not in ("", "0.0.0.0"):
                    return True
        except OSError:
            continue
    return False


def choose_mode(force_browser: bool) -> tuple[bool, str | None]:
    """(native?, reason-for-fallback). Native window needs pywebview (+ WebView2 on Windows)."""
    if force_browser:
        return False, None
    try:
        import webview  # noqa: F401
    except ImportError:
        return False, "pywebview is not installed; opening in your default browser instead."
    if not webview2_available():
        return False, ("The Microsoft Edge WebView2 runtime was not found; opening in your default browser instead. "
                       "Install it from https://developer.microsoft.com/microsoft-edge/webview2/ for the native window.")
    return True, None


def _notify_fallback(reason: str) -> None:
    if getattr(sys, "frozen", False) and sys.platform == "win32":
        try:
            import ctypes
            ctypes.windll.user32.MessageBoxW(0, reason, "ZeroPulse PR Review Agent", 0x40)  # type: ignore[attr-defined]
        except Exception:  # noqa: BLE001
            pass
    else:
        print(reason, file=sys.stderr)


def main(argv: list[str] | None = None) -> int:
    import argparse

    ap = argparse.ArgumentParser(description="ZeroPulse PR Review Agent desktop app")
    ap.add_argument("--browser", action="store_true", help="run in the default browser instead of a native window")
    ap.add_argument("--port", type=int, default=0, help="local port (default: a free port on 127.0.0.1)")
    # NiceGUI's native mode re-imports this module in a child process: do no heavy work there.
    if multiprocessing.current_process().name != "MainProcess":
        return 0
    args = ap.parse_args(argv)

    _ensure_std_streams()
    from core.logging_setup import setup_logging
    setup_logging(console=not getattr(sys, "frozen", False))
    native, reason = choose_mode(args.browser)
    if reason:
        _notify_fallback(reason)
    from dashboard.app import run_app
    run_app(native=native, port=args.port or _find_free_port())
    return 0


if __name__ == "__main__":
    multiprocessing.freeze_support()  # required for frozen Windows builds using multiprocessing (native window)
    sys.exit(main())
# NOTE: when imported as "__mp_main__" (native-window child process) nothing runs and we must NOT sys.exit().
