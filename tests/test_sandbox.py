import io
import os
import stat
import sys
import threading
import time
import zipfile
from pathlib import Path

import pytest

from core.sandbox.docker_runner import DockerRunner, host_env_for_docker_cli
from core.sandbox.result_parser import decide_status, parse_output
from core.sandbox.runner import PROFILES, UNAVAILABLE_MESSAGE, SandboxRequest, SandboxResult, UnavailableRunner
from core.schemas import TestFile
from core.review_pipeline import apply_sandbox_result

PY_OK = "collecting ...\n\n2 passed in 0.03s\n"
PY_FAIL = "FAILED tests/test_x.py::test_a - assert 1 == 2\n1 failed, 1 passed in 0.10s\n"
PY_NONE = "no tests ran in 0.01s\n"
JEST_OK = "Tests:       3 passed, 3 total\nTime:        1.5 s\n"
VITEST_FAIL = " Tests  1 failed | 2 passed (3)\n Duration  1.2s\n"


def _zip() -> bytes:
    b = io.BytesIO()
    with zipfile.ZipFile(b, "w") as z:
        z.writestr("repo-1/app/orders.py", "def f(): pass\n")
        z.writestr("repo-1/requirements.txt", "pytest\n")
    return b.getvalue()


def _req(**kw):
    d = dict(repo_zip=_zip(), test_path="tests/test_orders.py", test_content="def test_a():\n    assert True\n",
             language="python", framework="pytest", timeout=10)
    d.update(kw)
    return SandboxRequest(**d)


FAKE_DOCKER_PY = r"""
import os, sys, time
log, envfile = sys.argv[1], sys.argv[2]
args = sys.argv[3:]
with open(log, "a") as f:
    f.write(" ".join(args) + "\n")
with open(envfile, "w") as f:
    f.write("\n".join(f"{k}={v}" for k, v in sorted(os.environ.items())))
cmd, mode = (args[0] if args else ""), os.environ.get("FAKE_DOCKER_MODE", "")
if cmd == "info":
    print(os.environ.get("FAKE_DOCKER_OSTYPE", "linux")); sys.exit(0)
if cmd == "image":
    sys.exit(1 if os.environ.get("FAKE_IMAGE") == "missing" else 0)
if cmd == "run":
    if mode == "pass": print("2 passed in 0.03s"); sys.exit(0)
    if mode == "fail": print("1 failed, 1 passed in 0.10s"); sys.exit(1)
    if mode == "none": print("no tests ran in 0.01s"); sys.exit(5)
    if mode == "hang": time.sleep(30)
    if mode == "nomod": print("ModuleNotFoundError: No module named 'pytest'"); sys.exit(1)
    if mode == "flood":
        line = "A" * 60 + "\n"
        sys.stdout.write(line * 50000); sys.exit(0)
sys.exit(0)
"""


def make_fake_docker(tmp_path: Path):
    """A stand-in `docker` executable (cross-platform) that logs every invocation. Behaviour via env vars."""
    log = tmp_path / "docker.log"
    impl = tmp_path / "fake_docker_impl.py"
    impl.write_text(FAKE_DOCKER_PY, encoding="utf-8")
    envfile = tmp_path / "last_env.txt"
    if sys.platform == "win32":
        script = tmp_path / "docker.cmd"
        script.write_text(f'@"{sys.executable}" "{impl}" "{log}" "{envfile}" %*\r\n', encoding="utf-8")
    else:
        script = tmp_path / "docker"
        script.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "{log}" "{envfile}" "$@"\n', encoding="utf-8")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)
    log.touch()
    return script, log


@pytest.fixture
def fake_docker(tmp_path):
    return make_fake_docker(tmp_path)


# ------------------------------------------------------------------ parsing: never a false pass
def test_result_parser_python_and_js():
    p = parse_output("python", "pytest", PY_OK)
    assert (p.passed, p.failed) == (2, None) and p.duration == 0.03
    assert decide_status(0, p) == "passed"
    f = parse_output("python", "pytest", PY_FAIL)
    assert (f.passed, f.failed) == (1, 1) and decide_status(1, f) == "failed"
    n = parse_output("python", "pytest", PY_NONE)
    assert n.collected_nothing and decide_status(5, n) == "error"
    j = parse_output("javascript", "jest", JEST_OK)
    assert j.passed == 3 and decide_status(0, j) == "passed" and j.duration == 1.5
    v = parse_output("typescript", "vitest", VITEST_FAIL)
    assert (v.passed, v.failed) == (2, 1) and decide_status(1, v) == "failed"


def test_exit_zero_without_evidence_is_not_a_pass():
    assert decide_status(0, parse_output("python", "pytest", "")) == "error"
    assert decide_status(0, parse_output("python", "pytest", "0 passed")) == "error"
    assert decide_status(0, parse_output("python", "pytest", "1 passed, 1 error in 1s")) == "error"


# ------------------------------------------------------------------ command construction / safeguards
def test_run_args_contain_every_required_safeguard(tmp_path):
    r = DockerRunner(docker_bin="docker")
    args = r.build_run_args(name="n", workdir=tmp_path, image="python:3.11-slim", command=["python", "-m", "pytest"],
                            network=False, req=_req(memory_mb=512, cpus=0.5), env=PROFILES["python"].env)
    joined = " ".join(args)
    assert args[args.index("--network") + 1] == "none"
    assert "--cap-drop ALL" in joined and "no-new-privileges" in joined and "--read-only" in joined
    assert "--memory 512m" in joined and "--cpus 0.5" in joined and "--pids-limit" in joined
    assert args[args.index("--user") + 1] == "65534:65534"
    for forbidden in ("--privileged", "--env-file", "--volumes-from", "--pid", "--ipc", "--net=host", "--network=host"):
        assert forbidden not in args  # exact-token check ("--pids-limit" is allowed)
    assert "docker.sock" not in joined and "host" not in args
    mounts = [a for a in args if a.startswith("type=bind")]
    assert len(mounts) == 1 and str(tmp_path) in mounts[0]  # only the disposable work dir
    assert f"source={Path.home()}," not in joined and f"source={Path.home()}/" not in joined  # home itself is never mounted
    assert "--rm" in args
    net = r.build_run_args(name="n", workdir=tmp_path, image="i", command=["x"], network=True, req=_req(), env={})
    assert net[net.index("--network") + 1] == "bridge"


def test_docker_cli_env_never_contains_credentials(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_x")
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-or-x")
    monkeypatch.setenv("MY_PASSWORD", "p")
    env = host_env_for_docker_cli()
    assert not {"GITHUB_TOKEN", "OPENROUTER_API_KEY", "MY_PASSWORD"} & set(env)


# ------------------------------------------------------------------ behaviour with a fake docker
def test_passed_run_uses_network_none_and_cleans_up(fake_docker, monkeypatch):
    script, log = fake_docker
    monkeypatch.setenv("FAKE_DOCKER_MODE", "pass")
    monkeypatch.setenv("GITHUB_TOKEN", "ghp_secret_should_not_reach_docker")
    res = DockerRunner(docker_bin=str(script)).run(_req())
    assert res.status == "passed" and res.passed == 2 and res.runner == "docker"
    calls = log.read_text()
    run_lines = [l for l in calls.splitlines() if l.startswith("run ")]
    assert len(run_lines) == 1 and "--network none" in run_lines[0]  # no install phase without consent
    assert "rm -f zp-sandbox-" in calls  # container removed
    assert "ghp_secret_should_not_reach_docker" not in (script.parent / "last_env.txt").read_text()


def test_workdir_is_disposable(fake_docker, monkeypatch, tmp_path):
    script, _ = fake_docker
    monkeypatch.setenv("FAKE_DOCKER_MODE", "pass")
    root = tmp_path / "wd"
    root.mkdir()
    DockerRunner(docker_bin=str(script), workdir_root=root).run(_req())
    assert list(root.iterdir()) == []


def test_install_phase_only_with_consent_and_test_phase_still_offline(fake_docker, monkeypatch):
    script, log = fake_docker
    monkeypatch.setenv("FAKE_DOCKER_MODE", "pass")
    res = DockerRunner(docker_bin=str(script)).run(_req(install_dependencies=True))
    assert res.status == "passed"
    runs = [l for l in log.read_text().splitlines() if l.startswith("run ")]
    assert len(runs) == 2 and "--network bridge" in runs[0] and "pip install" in runs[0]
    assert "--network none" in runs[1] and "pytest" in runs[1] and "pip install" not in runs[1]


def test_failed_no_tests_and_missing_module(fake_docker, monkeypatch):
    script, _ = fake_docker
    r = DockerRunner(docker_bin=str(script))
    monkeypatch.setenv("FAKE_DOCKER_MODE", "fail")
    f = r.run(_req())
    assert f.status == "failed" and f.failed == 1
    monkeypatch.setenv("FAKE_DOCKER_MODE", "none")
    n = r.run(_req())
    assert n.status == "error" and "not verified" in n.output
    monkeypatch.setenv("FAKE_DOCKER_MODE", "nomod")
    m = r.run(_req())
    assert m.status == "error" and "Install dependencies" in m.output


def test_timeout_kills_and_removes_container(fake_docker, monkeypatch):
    script, log = fake_docker
    monkeypatch.setenv("FAKE_DOCKER_MODE", "hang")
    t0 = time.time()
    res = DockerRunner(docker_bin=str(script)).run(_req(timeout=1))
    assert res.status == "timeout" and time.time() - t0 < 10
    assert log.read_text().count("rm -f") >= 1


def test_cancellation_stops_run(fake_docker, monkeypatch):
    script, log = fake_docker
    monkeypatch.setenv("FAKE_DOCKER_MODE", "hang")
    ev = threading.Event()
    threading.Timer(0.6, ev.set).start()
    res = DockerRunner(docker_bin=str(script)).run(_req(timeout=30), ev)
    assert res.status == "cancelled" and "rm -f" in log.read_text()


def test_output_is_capped(fake_docker, monkeypatch):
    script, _ = fake_docker
    monkeypatch.setenv("FAKE_DOCKER_MODE", "flood")
    res = DockerRunner(docker_bin=str(script)).run(_req(max_output_bytes=5000))
    assert len(res.output) < 8000 and "truncated" in res.output


def test_image_not_downloaded_without_consent(fake_docker, monkeypatch):
    script, log = fake_docker
    monkeypatch.setenv("FAKE_IMAGE", "missing")
    monkeypatch.setenv("FAKE_DOCKER_MODE", "pass")
    res = DockerRunner(docker_bin=str(script)).run(_req())
    assert res.status == "error" and "docker pull" in res.output
    assert not any(l.startswith("run ") for l in log.read_text().splitlines())


def test_unsafe_test_path_and_unsupported_language_rejected(fake_docker, monkeypatch):
    script, log = fake_docker
    r = DockerRunner(docker_bin=str(script))
    assert r.run(_req(test_path="../../evil.py")).status == "error"
    assert r.run(_req(language="cobol")).status == "error"
    assert not any(l.startswith("run ") for l in log.read_text().splitlines())


def test_unavailable_docker_never_claims_execution(tmp_path):
    res = DockerRunner(docker_bin=str(tmp_path / "does-not-exist")).run(_req())
    assert res.status == "unavailable" and UNAVAILABLE_MESSAGE in res.output and not res.executed
    assert UnavailableRunner().run(_req()).output == UNAVAILABLE_MESSAGE
    tf = TestFile(filename="t.py", language="python", framework="pytest", content="x")
    apply_sandbox_result(tf, res)
    assert tf.execution_status == "not_run" and tf.artifact_state == "generated"


def test_windows_container_mode_is_rejected(tmp_path, monkeypatch):
    s, _ = make_fake_docker(tmp_path)
    monkeypatch.setenv("FAKE_DOCKER_OSTYPE", "windows")
    ok, reason = DockerRunner(docker_bin=str(s)).available()
    assert not ok and "Linux containers" in reason


def test_apply_result_semantics():
    tf = TestFile(filename="t.py", language="python", framework="pytest", content="x")
    apply_sandbox_result(tf, SandboxResult("passed", 2, 0, 1.0, "ok", "docker"))
    assert (tf.execution_status, tf.artifact_state, tf.tests_passed) == ("passed", "executed", 2)
    tf2 = TestFile(filename="t.py", language="python", framework="pytest", content="x")
    apply_sandbox_result(tf2, SandboxResult("timeout", output="t", runner="docker"))
    assert tf2.execution_status == "error" and tf2.artifact_state == "generated"


def _fake_cli(tmp_path, body_py: str):
    impl = tmp_path / "impl.py"
    impl.write_text(body_py, encoding="utf-8")
    if sys.platform == "win32":
        s = tmp_path / "docker.cmd"
        s.write_text(f'@"{sys.executable}" "{impl}" %*\r\n', encoding="utf-8")
    else:
        s = tmp_path / "docker"
        s.write_text(f'#!/bin/sh\nexec "{sys.executable}" "{impl}" "$@"\n', encoding="utf-8")
        s.chmod(0o755)
    return str(s)


@pytest.mark.parametrize("stderr,expect", [
    ("error during connect: this error may indicate that the docker daemon is not running", "engine is not running"),
    ("Cannot connect to the Docker daemon at unix:///var/run/docker.sock. Is the docker daemon running?", "engine is not running"),
    ("permission denied while trying to connect", "refused access"),
])
def test_availability_explains_why(tmp_path, stderr, expect):
    cli = _fake_cli(tmp_path, f"import sys; sys.stderr.write({stderr!r}); sys.exit(1)\n")
    ok, reason = DockerRunner(docker_bin=cli).available()
    assert not ok and expect in reason and UNAVAILABLE_MESSAGE in reason


def test_missing_docker_says_not_installed(tmp_path):
    ok, reason = DockerRunner(docker_bin=str(tmp_path / "nope" / "docker")).available()
    assert not ok and "not installed" in reason


def test_failed_check_is_not_cached_so_starting_docker_is_detected(tmp_path):
    flag = tmp_path / "up"
    cli = _fake_cli(tmp_path, f"import os,sys\nif os.path.exists({str(flag)!r}): print('linux'); sys.exit(0)\n"
                              "sys.stderr.write('error during connect'); sys.exit(1)\n")
    r = DockerRunner(docker_bin=cli)
    assert r.available()[0] is False
    flag.write_text("1")
    assert r.available() == (True, "")
