"""Platform routing, Keychain failure semantics, and server lifecycle regression tests."""
import sys
from unittest.mock import Mock

import pytest

from core import paths, security
from core.config import ConfigManager
from core.macos_desktop import stop_server, wait_ready


def test_macos_paths_and_override(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.delenv("ZEROPULSE_DATA_DIR")
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "ignored"))
    assert str(paths.data_dir()).replace("\\", "/").endswith("Library/Application Support/ZeroPulse/PulseReview")
    monkeypatch.setenv("ZEROPULSE_DATA_DIR", str(tmp_path))
    assert paths.data_dir() == tmp_path


def test_backend_routing_preserves_dpapi(monkeypatch):
    monkeypatch.setattr(sys, "platform", "win32")
    assert isinstance(security.default_secret_store(), security.DpapiSecretStore)
    expected = object()
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(security, "KeychainSecretStore", lambda: expected)
    assert security.default_secret_store() is expected
    monkeypatch.setattr(sys, "platform", "linux")
    assert isinstance(security.default_secret_store(), security.MemorySecretStore)


def test_all_saved_credentials_use_keychain_and_not_files(tmp_path):
    class Backend:
        entries = {}
        def set_password(self, service, ref, value):
            self.entries[service, ref] = value
        def get_password(self, service, ref):
            return self.entries.get((service, ref))
        def delete_password(self, service, ref):
            del self.entries[service, ref]
    backend = Backend()
    store = security.KeychainSecretStore(backend)
    mgr = ConfigManager(tmp_path / "config.json", store)
    mgr.set_github_oauth("access-value", scopes="repo", refresh_token="refresh-value", expires_at=None)
    mgr.set_openrouter_key("provider-value")
    assert mgr.get_github_token() == "access-value"
    assert mgr.get_github_refresh_token() == "refresh-value"
    assert mgr.get_openrouter_key() == "provider-value"
    assert all(s == store.SERVICE for s, _ in backend.entries)
    raw = mgr.path.read_text()
    assert all(v not in raw for v in backend.entries.values())
    assert list(tmp_path.iterdir()) == [mgr.path]
    mgr.clear_github_token()
    mgr.clear_openrouter_key()
    store.delete("already-absent")
    assert backend.entries == {}


@pytest.mark.parametrize("operation", ["get", "set", "delete"])
def test_keychain_denied_never_falls_back_or_leaks(operation, tmp_path):
    backend = Mock()
    backend.get_password.return_value = "present"
    method = {"get": "get_password", "set": "set_password", "delete": "delete_password"}[operation]
    getattr(backend, method).side_effect = RuntimeError("sensitive-backend-value")
    store = security.KeychainSecretStore(backend)
    with pytest.raises(RuntimeError, match="Unlock your login keychain") as error:
        getattr(store, operation)("ref", *(["secret"] if operation == "set" else []))
    assert "sensitive-backend-value" not in str(error.value)
    assert list(tmp_path.iterdir()) == []


def test_dead_server_does_not_wait_forever():
    process = Mock()
    process.is_alive.return_value = False
    with pytest.raises(RuntimeError, match="could not start"):
        wait_ready(process, "http://127.0.0.1:1")


def test_shutdown_graceful_then_force_cleanup():
    process, stop = Mock(), Mock()
    process.is_alive.side_effect = [True, True]
    stop_server(process, stop)
    stop.set.assert_called_once()
    process.terminate.assert_called_once()
    process.kill.assert_called_once()
    assert process.join.call_count == 3


def test_docker_mac_start_is_explicit_open(monkeypatch):
    from core.sandbox import docker_setup
    monkeypatch.setattr(sys, "platform", "darwin")
    monkeypatch.setattr(docker_setup, "docker_desktop_exe", lambda: paths.Path("/Applications/Docker.app"))
    run = Mock()
    monkeypatch.setattr(docker_setup.subprocess, "Popen", run)
    assert docker_setup.start_docker_desktop()
    run.assert_called_once_with(["/usr/bin/open", str(paths.Path("/Applications/Docker.app"))])
