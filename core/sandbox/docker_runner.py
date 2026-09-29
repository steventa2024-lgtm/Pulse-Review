"""Docker-based isolated execution of generated tests (Linux containers).

Safeguards: no privileged mode, no docker.sock, no host credentials or home mounts, no PulseReview secrets in
the container environment, network disabled for test execution, CPU/memory/pid limits, read-only root FS,
timeout with forced cleanup, output cap, disposable working directory.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import uuid
from pathlib import Path, PurePosixPath

from ..github_client import GitHubError, safe_extract_zip
from ..security import redact_secrets, safe_relative_path
from .result_parser import decide_status, parse_output
from .runner import PROFILES, UNAVAILABLE_MESSAGE, SandboxRequest, SandboxResult, SandboxRunner

log = logging.getLogger(__name__)
_SECRET_ENV = re.compile(r"(?i)(token|secret|passw|api[_-]?key|credential|auth)")


_NO_WINDOW = {"creationflags": 0x08000000} if sys.platform == "win32" else {}  # CREATE_NO_WINDOW: no console flashes


def find_docker() -> str | None:
    """docker on PATH, else the standard Docker Desktop install location (PATH is often stale after installing)."""
    found = shutil.which("docker")
    if found:
        return found
    if sys.platform == "win32":
        for base in (os.environ.get("ProgramFiles", r"C:\Program Files"), os.environ.get("ProgramW6432", "")):
            cand = Path(base) / "Docker" / "Docker" / "resources" / "bin" / "docker.exe"
            if base and cand.is_file():
                return str(cand)
    elif sys.platform == "darwin":
        cand = Path("/Applications/Docker.app/Contents/Resources/bin/docker")
        if cand.is_file():
            return str(cand)
    return None


def host_env_for_docker_cli() -> dict[str, str]:
    """Environment for the docker CLI itself: no credential-looking variables."""
    return {k: v for k, v in os.environ.items() if not _SECRET_ENV.search(k)}


class DockerRunner(SandboxRunner):
    name = "docker"

    def __init__(self, docker_bin: str | None = None, workdir_root: Path | None = None) -> None:
        self.docker = docker_bin or find_docker() or "docker"
        self.workdir_root = workdir_root
        self._availability: tuple[bool, str] | None = None

    # -- helpers ----------------------------------------------------------------------
    def _run_cli(self, args: list[str], timeout: float = 15) -> subprocess.CompletedProcess[str]:
        return subprocess.run([self.docker, *args], capture_output=True, text=True, timeout=timeout,
                              env=host_env_for_docker_cli(), encoding="utf-8", errors="replace", **_NO_WINDOW)

    def available(self) -> tuple[bool, str]:
        """(usable, reason). A failed check is not cached, so starting Docker later is picked up."""
        if self._availability is not None and self._availability[0]:
            return self._availability
        if not (shutil.which(self.docker) or Path(self.docker).is_file()):
            return self._set(False, "Docker is not installed (or not found). Install Docker Desktop, then restart PulseReview. "
                                    + UNAVAILABLE_MESSAGE)
        try:
            p = self._run_cli(["info", "--format", "{{.OSType}}"], timeout=25)
        except subprocess.TimeoutExpired:
            return self._set(False, "Docker did not respond (the engine may still be starting). " + UNAVAILABLE_MESSAGE)
        except (subprocess.SubprocessError, OSError) as exc:
            return self._set(False, f"Could not run Docker ({exc}). " + UNAVAILABLE_MESSAGE)
        out = (p.stdout or "").strip().lower()
        err = (p.stderr or "").strip()
        if p.returncode != 0:
            low = err.lower()
            if "permission denied" in low or "access is denied" in low:
                why = "Docker refused access. Make sure your user is allowed to use Docker (docker-users group)."
            elif any(k in low for k in ("cannot connect", "error during connect", "is the docker daemon running",
                                        "pipe/docker", "dockerdesktoplinuxengine", "the system cannot find the file")):
                why = "Docker Desktop is installed but its engine is not running. Start Docker Desktop and wait until it says “Engine running”."
            else:
                why = f"Docker returned an error: {err[:200] or 'exit code ' + str(p.returncode)}."
            return self._set(False, why + " " + UNAVAILABLE_MESSAGE)
        if out != "linux":
            return self._set(False, "Docker is in Windows-containers mode. Right-click the Docker tray icon → “Switch to Linux containers…”. "
                                    + UNAVAILABLE_MESSAGE)
        return self._set(True, "")

    def _set(self, ok: bool, reason: str) -> tuple[bool, str]:
        self._availability = (ok, reason)
        return self._availability

    def image_present(self, image: str) -> bool:
        try:
            return self._run_cli(["image", "inspect", image], timeout=15).returncode == 0
        except (subprocess.SubprocessError, OSError):
            return False

    def ensure_image(self, profile, allow_pull: bool) -> tuple[str | None, str]:
        """Image to run tests in, preparing the one-time tool image (e.g. python + pytest) if needed.

        Returns (image, note). image is None when nothing usable exists and pulling was not allowed.
        """
        if profile.runner_image and self.image_present(profile.runner_image):
            return profile.runner_image, ""
        base_ok = self.image_present(profile.image)
        if not base_ok and not allow_pull:
            return None, (f"The Docker image '{profile.image}' is not on this PC yet. Tick 'Allow Docker to download the base "
                          f"image' or run `docker pull {profile.image}` once, then try again.")
        if profile.runner_image and profile.runner_dockerfile:
            try:
                p = subprocess.run([self.docker, "build", "-t", profile.runner_image, "-"], input=profile.runner_dockerfile,
                                   capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                                   env=host_env_for_docker_cli(), **_NO_WINDOW)
                if p.returncode == 0:
                    return profile.runner_image, f"=== prepared sandbox image {profile.runner_image} (one-time) ==="
                log.warning("Sandbox image build failed: %s", (p.stderr or p.stdout)[-500:])
                note = "=== could not prepare the sandbox tool image; using the base image (enable dependency install if the test runner is missing) ==="
            except (subprocess.SubprocessError, OSError) as exc:
                note = f"=== could not prepare the sandbox tool image ({exc}); using the base image ==="
            return profile.image, note
        return profile.image, ""

    def build_run_args(self, *, name: str, workdir: Path, image: str, command: list[str], network: bool,
                       req: SandboxRequest, env: dict[str, str]) -> list[str]:
        """The exact `docker run` argument list (public so tests can assert the safety flags)."""
        args = [
            "run", "--rm", "--name", name,
            "--network", "bridge" if network else "none",
            "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
            "--pids-limit", "256",
            "--memory", f"{req.memory_mb}m", "--memory-swap", f"{req.memory_mb}m",
            "--cpus", str(req.cpus),
            "--read-only", "--tmpfs", "/tmp:rw,noexec,nosuid,size=256m",
            "--user", "65534:65534",
            "--mount", f"type=bind,source={workdir},target=/work",
            "--workdir", "/work",
            "-e", "HOME=/tmp",
        ]
        for k, v in env.items():
            args += ["-e", f"{k}={v}"]
        args += [image, *command]
        return args

    def _exec(self, args: list[str], name: str, timeout: int, max_bytes: int,
              cancel: threading.Event | None) -> tuple[int | None, str, str]:
        """Run the container; returns (exit_code, output, outcome) where outcome in ok|timeout|cancelled."""
        proc = subprocess.Popen([self.docker, *args], stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                env=host_env_for_docker_cli(), **_NO_WINDOW)
        chunks: list[bytes] = []
        size = 0

        def reader() -> None:
            nonlocal size
            assert proc.stdout is not None
            for line in iter(proc.stdout.readline, b""):
                if size < max_bytes:
                    chunks.append(line)
                    size += len(line)

        t = threading.Thread(target=reader, daemon=True)
        t.start()
        deadline = time.monotonic() + timeout
        outcome = "ok"
        try:
            while proc.poll() is None:
                if cancel is not None and cancel.is_set():
                    outcome = "cancelled"
                    break
                if time.monotonic() > deadline:
                    outcome = "timeout"
                    break
                time.sleep(0.2)
        finally:
            if proc.poll() is None:
                self._cleanup_container(name)
                try:
                    proc.kill()
                except OSError:
                    pass
            self._cleanup_container(name)
        t.join(timeout=3)
        text = b"".join(chunks).decode("utf-8", errors="replace")
        if size >= max_bytes:
            text += f"\n… [output truncated at {max_bytes} bytes]"
        return proc.returncode, text, outcome

    def _cleanup_container(self, name: str) -> None:
        try:
            self._run_cli(["rm", "-f", name], timeout=15)
        except (subprocess.SubprocessError, OSError):
            log.warning("Could not remove sandbox container %s", name)

    # -- main entry -------------------------------------------------------------------
    def run(self, req: SandboxRequest, cancel: threading.Event | None = None) -> SandboxResult:
        ok, reason = self.available()
        if not ok:
            return SandboxResult("unavailable", output=reason or UNAVAILABLE_MESSAGE, runner=self.name)
        profile = PROFILES.get(req.language)
        if profile is None:
            return SandboxResult("error", output=f"Sandbox execution is not implemented for {req.language}. "
                                 f"Supported: {', '.join(sorted(PROFILES))}.", runner=self.name)
        rel = safe_relative_path(req.test_path)
        if rel is None:
            return SandboxResult("error", output="Unsafe test file path.", runner=self.name)
        image, prep_note = self.ensure_image(profile, req.allow_pull)
        if image is None:
            return SandboxResult("error", runner=self.name, output=prep_note)
        root = Path(tempfile.mkdtemp(prefix="zp-sandbox-", dir=self.workdir_root))
        started = time.monotonic()
        try:
            try:
                repo_root = safe_extract_zip(req.repo_zip, root / "repo")
            except (GitHubError, OSError, Exception) as exc:  # noqa: BLE001 - corrupt/hostile archive
                return SandboxResult("error", output=f"Could not prepare the repository archive: {exc}", runner=self.name)
            target = (repo_root / PurePosixPath(rel)).resolve()
            if repo_root.resolve() not in target.parents:
                return SandboxResult("error", output="Test path escapes the repository.", runner=self.name)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(req.test_content, encoding="utf-8")
            self._make_writable(repo_root)
            outputs: list[str] = [prep_note] if prep_note else []
            base = f"zp-sandbox-{uuid.uuid4().hex[:10]}"
            if req.install_dependencies:
                name = base + "-install"
                args = self.build_run_args(name=name, workdir=repo_root, image=image,
                                           command=profile.install_cmd(""), network=True, req=req, env=profile.env)
                code, out, outcome = self._exec(args, name, req.timeout, req.max_output_bytes, cancel)
                outputs.append("=== dependency installation (network enabled, isolated) ===\n" + out)
                if outcome != "ok" or code != 0:
                    status = {"timeout": "timeout", "cancelled": "cancelled"}.get(outcome, "error")
                    return SandboxResult(status, output=redact_secrets("\n".join(outputs))[0], runner=self.name,
                                         duration_seconds=time.monotonic() - started)
            name = base + "-test"
            args = self.build_run_args(name=name, workdir=repo_root, image=image,
                                       command=profile.test_cmd(rel, req.framework), network=False, req=req, env=profile.env)
            code, out, outcome = self._exec(args, name, req.timeout, req.max_output_bytes, cancel)
            outputs.append("=== test execution (network disabled) ===\n" + out)
            text = redact_secrets("\n".join(outputs))[0]
            duration = time.monotonic() - started
            if outcome == "timeout":
                return SandboxResult("timeout", output=text + f"\nTimed out after {req.timeout}s.", runner=self.name, duration_seconds=duration)
            if outcome == "cancelled":
                return SandboxResult("cancelled", output=text, runner=self.name, duration_seconds=duration)
            parsed = parse_output(req.language, req.framework, out)
            status = decide_status(code if code is not None else -1, parsed)
            if parsed.collected_nothing:
                status = "error"
                text += "\nNo tests were collected — the test was not verified."
            if status == "error" and not req.install_dependencies and re.search(r"No module named|Cannot find module|not found", out):
                text += "\nHint: dependencies are missing. Re-run with 'Install dependencies in the sandbox' enabled."
            return SandboxResult(status, passed=parsed.passed, failed=parsed.failed,  # type: ignore[arg-type]
                                 duration_seconds=parsed.duration or duration, output=text, runner=self.name)
        finally:
            shutil.rmtree(root, ignore_errors=True)

    @staticmethod
    def _make_writable(path: Path) -> None:
        for p in [path, *path.rglob("*")]:
            try:
                os.chmod(p, 0o777 if p.is_dir() else 0o666)
            except OSError:
                pass


def default_runner() -> SandboxRunner:
    return DockerRunner()
