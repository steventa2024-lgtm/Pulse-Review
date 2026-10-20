"""Test the actual packaged app outside the checkout, twice; do not mock Keychain.

Requires a logged-in macOS GUI session and an unlocked login keychain. Fails if
native rendering is unavailable; browser fallback is not a native test pass.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tempfile
import time
from urllib.request import urlopen


def main(app: Path) -> None:
    assert sys.platform == "darwin"
    exe = app.resolve() / "Contents/MacOS/PulseReview"
    reports = Path(__file__).resolve().parents[1] / "build/mac"
    reports.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="pulsereview-smoke-") as scratch:
        data = Path(scratch) / "data"
        env = {k: v for k, v in os.environ.items() if not k.startswith("PYTEST_") and
               k not in ("GITHUB_TOKEN", "OPENROUTER_API_KEY", "PYTHONPATH", "PYTHONHOME")}
        env["ZEROPULSE_DATA_DIR"] = str(data)
        subprocess.run([str(exe), "--diagnostics"], env=env, cwd=scratch, check=True, timeout=90)
        diagnostics = json.loads((data / "diagnostics.json").read_text())
        for attempt in (1, 2):
            with socket.socket() as sock:
                sock.bind(("127.0.0.1", 0))
                port = sock.getsockname()[1]
            report = reports / f"native-smoke-{attempt}.json"
            report.unlink(missing_ok=True)
            process = subprocess.Popen([str(exe), "--port", str(port), "--native-smoke-report", str(report)],
                                       env=env, cwd=scratch, start_new_session=True)
            try:
                code = process.wait(timeout=240)
                assert code == 0, f"Native app exited {code}"
                assert json.loads(report.read_text())["status"] == "passed"
            finally:
                if process.poll() is None:
                    # Kill only this test's process group, including its server.
                    import signal
                    os.killpg(process.pid, signal.SIGTERM)
                    try:
                        process.wait(timeout=15)
                    except subprocess.TimeoutExpired:
                        os.killpg(process.pid, signal.SIGKILL)
                        process.wait(timeout=5)
            time.sleep(1)
            with socket.socket() as probe:
                assert probe.connect_ex(("127.0.0.1", port)) != 0, "Dashboard server survived app close"
        assert (data / "reviews.db").is_file()
        assert json.loads((data / "config.json").read_text())["app"]["watch_poll_minutes"] == 7
        (reports / "packaged-smoke.json").write_text(json.dumps({
            **diagnostics, "native_launch_and_reopen": "passed twice",
            "server_shutdown": "passed twice", "settings_across_launches": "passed",
            "live_github_ollama_docker": "not tested; credentials/services not supplied",
        }, indent=2))


if __name__ == "__main__":
    main(Path(sys.argv[1]))
