"""Help the user install / start Docker Desktop on Windows. Every action here is triggered by an explicit click."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Callable, Iterator

WINGET_ID = "Docker.DockerDesktop"
_NO_WINDOW = 0x08000000 if sys.platform == "win32" else 0


def docker_desktop_exe() -> Path | None:
    if sys.platform != "win32":
        return None
    for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")):
        if base:
            p = Path(base) / "Docker" / "Docker" / "Docker Desktop.exe"
            if p.is_file():
                return p
    return None


def winget_path() -> str | None:
    return shutil.which("winget") if sys.platform == "win32" else None


def install_command() -> list[str]:
    return ["winget", "install", "--exact", "--id", WINGET_ID, "--source", "winget",
            "--accept-package-agreements", "--accept-source-agreements", "--disable-interactivity"]


def run_install(on_line: Callable[[str], None], runner: Callable[..., subprocess.Popen] = subprocess.Popen) -> int:
    """Run winget (it shows its own Windows admin prompt). Streams output lines; returns the exit code."""
    cmd = install_command()
    cmd[0] = winget_path() or cmd[0]
    proc = runner(cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                  creationflags=_NO_WINDOW)
    assert proc.stdout is not None
    for line in _lines(proc.stdout):
        on_line(line)
    return proc.wait()


def _lines(stream) -> Iterator[str]:
    for raw in stream:
        line = raw.rstrip().split("\r")[-1].strip()  # winget redraws progress bars with \r
        if line and not set(line) <= set("-\\|/█▒ "):
            yield line


def start_docker_desktop() -> bool:
    exe = docker_desktop_exe()
    if exe is None:
        return False
    subprocess.Popen([str(exe)], creationflags=_NO_WINDOW | 0x00000008)  # DETACHED_PROCESS
    return True
