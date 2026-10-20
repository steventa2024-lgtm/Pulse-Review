import os
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


@pytest.fixture(autouse=True)
def isolated_data_dir(tmp_path, monkeypatch):
    """Every test gets its own APPDATA-equivalent; nothing touches the real user profile."""
    d = tmp_path / "appdata"
    monkeypatch.setenv("ZEROPULSE_DATA_DIR", str(d))
    for k in ("GITHUB_TOKEN", "OPENROUTER_API_KEY"):
        monkeypatch.delenv(k, raising=False)
    if sys.platform == "darwin":
        # Unit tests must not read or change a developer's login Keychain.
        # The packaged diagnostics exercise a real disposable Keychain entry.
        from core.security import MemorySecretStore
        monkeypatch.setattr("core.config.default_secret_store", MemorySecretStore)
    return d
