"""macOS Cocoa/WKWebView on the main thread; same dashboard in a managed server.

Windows continues to use NiceGUI's existing native launcher. The Mac parent owns
the server lifetime, including a visible Quit control for the browser fallback.
"""
from __future__ import annotations

import asyncio
import json
import logging
import multiprocessing as mp
import os
import subprocess
import time
import webbrowser
from pathlib import Path
from urllib.request import urlopen

log = logging.getLogger(__name__)


def _serve(port: int, stop, parent_pid: int) -> None:
    from main import _ensure_std_streams
    from core.logging_setup import setup_logging
    _ensure_std_streams()
    setup_logging(console=False)
    from nicegui import app, background_tasks
    from dashboard.app import run_app

    async def monitor() -> None:
        while not stop.is_set() and os.getppid() == parent_pid:
            await asyncio.sleep(0.25)
        app.shutdown()

    app.on_startup(lambda: background_tasks.create(monitor()))
    run_app(native=False, port=port, show=False)


def wait_ready(process, url: str, timeout: float = 90) -> None:
    deadline = time.monotonic() + timeout
    while process.is_alive() and time.monotonic() < deadline:
        try:
            with urlopen(url + "/assets/style.css", timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.2)
    raise RuntimeError("The dashboard could not start. See Application Support/ZeroPulse/PulseReview/logs/app.log.")


def stop_server(process, stop) -> None:
    stop.set()
    process.join(timeout=12)
    if process.is_alive():
        process.terminate()
        process.join(timeout=5)
    if process.is_alive():
        process.kill()
        process.join(timeout=5)


def browser_session(url: str) -> None:
    webbrowser.open(url, new=2)
    # A Finder launch has no console. Keep an explicit, visible control to stop
    # the loopback server; closing a browser tab alone is not a reliable signal.
    subprocess.run(["/usr/bin/osascript", "-e",
                    'display dialog "PulseReview is running in your browser. '
                    'Keep this dialog open while using the dashboard. '
                    'Choose Quit when finished to stop PulseReview." '
                    'with title "PulseReview — Browser Mode" buttons {"Quit"} default button "Quit"'],
                   check=True)


def _native_smoke(window, url: str, report: str) -> None:
    """Exercise the packaged WKWebView; no test services or remote API fixtures."""
    results = {}
    try:
        for route, text in [("/", "Dashboard"), ("/review/new", "New review"),
                            ("/code", "Code reviewer"), ("/history", "Review history"), ("/watch", "Watched repositories"),
                            ("/testlab", "Test lab"), ("/settings", "Settings")]:
            window.load_url(url + route)
            deadline = time.monotonic() + 30
            while time.monotonic() < deadline:
                if window.evaluate_js("typeof Vue !== 'undefined' && location.pathname === " + json.dumps(route) +
                                      " && document.querySelector('.zp-h1')?.innerText === " + json.dumps(text)):
                    results[route] = "passed"
                    break
                time.sleep(0.25)
            else:
                raise RuntimeError("WKWebView page did not render: " + route)
        results["status"] = "passed"
    except Exception as exc:
        results.update(status="failed", error=str(exc))
    finally:
        Path(report).write_text(json.dumps(results, indent=2), encoding="utf-8")
        window.destroy()


def run_desktop(*, port: int, browser: bool = False, smoke_report: str | None = None) -> int:
    if smoke_report and not os.environ.get("ZEROPULSE_DATA_DIR"):
        raise RuntimeError("Native smoke testing requires a scratch ZEROPULSE_DATA_DIR")
    context = mp.get_context("spawn")
    stop = context.Event()
    process = context.Process(target=_serve, args=(port, stop, os.getpid()), name="PulseReview-dashboard")
    process.start()
    url = f"http://127.0.0.1:{port}"
    try:
        wait_ready(process, url)
        if browser:
            browser_session(url)
        else:
            try:
                import webview
                webview.settings["ALLOW_DOWNLOADS"] = True
                window = webview.create_window("PulseReview", url, width=1440, height=900, min_size=(900, 600))
                if smoke_report:
                    webview.start(_native_smoke, (window, url, smoke_report), gui="cocoa", debug=False)
                else:
                    webview.start(gui="cocoa", debug=False)
            except Exception:
                if smoke_report:
                    raise  # CI must never pass by silently using the browser fallback.
                log.warning("Native macOS window unavailable; starting local browser fallback")
                browser_session(url)
        return 0
    finally:
        stop_server(process, stop)
