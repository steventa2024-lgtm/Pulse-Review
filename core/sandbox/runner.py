"""Sandbox runner interface. Untrusted PR code is only ever executed by a SandboxRunner implementation
that provides isolation (see docker_runner.py). The Windows host never runs repository code directly."""
from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Callable, Literal

UNAVAILABLE_MESSAGE = "Sandbox unavailable — generated test has not been executed."

SandboxStatus = Literal["passed", "failed", "error", "timeout", "unavailable", "cancelled"]


@dataclass
class LanguageProfile:
    """Extension point: add an entry to PROFILES to support another language/framework."""
    language: str
    image: str
    install_cmd: Callable[[str], list[str]]  # (repo_root_listing_hint) -> command (run WITH network, if consented)
    test_cmd: Callable[[str, str], list[str]]  # (test_path, framework) -> command (run WITHOUT network)
    env: dict[str, str] = field(default_factory=dict)
    # Optional tool image built once from `image` (trusted Dockerfile only — never repository code),
    # e.g. to have the test runner itself (pytest) available without installing anything per run.
    runner_image: str | None = None
    runner_dockerfile: str | None = None


def _py_install(_: str) -> list[str]:
    return ["sh", "-c", "pip install --no-input --disable-pip-version-check --target /work/.zp_deps pytest "
                        "&& if [ -f requirements.txt ]; then pip install --no-input --disable-pip-version-check --target /work/.zp_deps -r requirements.txt; fi"]


def _js_install(_: str) -> list[str]:
    return ["sh", "-c", "if [ -f package-lock.json ]; then npm ci --ignore-scripts --no-audit --no-fund; "
                        "else npm install --ignore-scripts --no-audit --no-fund; fi"]


def _js_test(path: str, framework: str) -> list[str]:
    if framework == "vitest":
        return ["npx", "--no-install", "vitest", "run", path]
    if framework == "mocha":
        return ["npx", "--no-install", "mocha", path]
    return ["npx", "--no-install", "jest", "--ci", path]


PROFILES: dict[str, LanguageProfile] = {
    "python": LanguageProfile(
        "python", "python:3.11-slim", _py_install,
        lambda path, fw: ["python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "--no-header", path],
        env={"PYTHONPATH": "/work:/work/src:/work/.zp_deps", "PYTHONDONTWRITEBYTECODE": "1"},
        runner_image="zeropulse/sandbox-python:3.11-v1",
        runner_dockerfile="FROM python:3.11-slim\nRUN pip install --no-cache-dir --disable-pip-version-check pytest\n"),
    "javascript": LanguageProfile("javascript", "node:20-slim", _js_install, _js_test, env={"CI": "1"}),
    "typescript": LanguageProfile("typescript", "node:20-slim", _js_install, _js_test, env={"CI": "1"}),
}


@dataclass
class SandboxRequest:
    repo_zip: bytes
    test_path: str  # repo-relative POSIX path
    test_content: str
    language: str
    framework: str
    install_dependencies: bool = False  # explicit user consent: network ON during install only
    allow_pull: bool = False  # explicit consent to let Docker pull a missing base image
    timeout: int = 180
    memory_mb: int = 1024
    cpus: float = 1.0
    max_output_bytes: int = 200_000


@dataclass
class SandboxResult:
    status: SandboxStatus
    passed: int | None = None
    failed: int | None = None
    duration_seconds: float | None = None
    output: str = ""
    runner: str = ""

    @property
    def executed(self) -> bool:
        return self.status in ("passed", "failed")


class SandboxRunner(ABC):
    name = "abstract"

    @abstractmethod
    def available(self) -> tuple[bool, str]:
        """(usable, reason-if-not)."""

    @abstractmethod
    def run(self, req: SandboxRequest, cancel: threading.Event | None = None) -> SandboxResult: ...


class UnavailableRunner(SandboxRunner):
    name = "none"

    def __init__(self, reason: str = UNAVAILABLE_MESSAGE) -> None:
        self.reason = reason

    def available(self) -> tuple[bool, str]:
        return False, self.reason

    def run(self, req: SandboxRequest, cancel: threading.Event | None = None) -> SandboxResult:
        return SandboxResult("unavailable", output=self.reason, runner=self.name)
