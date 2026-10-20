"""Opt-in packaged smoke check; isolated data dir required, no real credentials."""
from __future__ import annotations

import json
import os
import uuid


def run_diagnostics() -> int:
    from core.config import ConfigManager
    from core.db import Database
    from core.paths import data_dir
    from core.security import KeychainSecretStore

    if not os.environ.get("ZEROPULSE_DATA_DIR"):
        raise RuntimeError("Diagnostics requires a scratch ZEROPULSE_DATA_DIR")
    store = KeychainSecretStore()
    ref, value = "diagnostic-" + uuid.uuid4().hex, uuid.uuid4().hex
    try:
        store.set(ref, value)
        assert store.get(ref) == value
    finally:
        store.delete(ref)
    assert store.get(ref) is None
    mgr = ConfigManager(secrets=store)
    mgr.update(provider="ollama", app={"watch_poll_minutes": 7})
    assert ConfigManager(secrets=store).config.app.watch_poll_minutes == 7
    db = Database()
    db.add_watched_repo("octocat/Hello-World")
    assert Database().list_watched_repos()[0]["repo"] == "octocat/Hello-World"
    rid = db.create_review(repo="octocat/Hello-World", pr_number=1,
                           pr_url="https://github.com/octocat/Hello-World/pull/1",
                           provider="ollama", model="diagnostic-only", status="completed")
    db.update_review(rid, summary="Local persistence diagnostic; no AI or GitHub calls made")
    assert Database().get_review(rid)["status"] == "completed"
    db.set_pref("mac_diagnostic_review", rid)
    (data_dir() / "diagnostics.json").write_text(json.dumps({
        "keychain": "passed (temporary entry created, read, deleted)",
        "settings": "passed", "watched_repos": "passed", "review_history": "passed (synthetic record)",
    }, indent=2), encoding="utf-8")
    return 0
