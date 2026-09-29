"""Runs the real dashboard + real pipeline with fake GitHub/LLM injected. Test-control routes live under /__test.

Usage: python -m tests.ui.launcher PORT     (ZEROPULSE_DATA_DIR must point at a scratch dir)
"""
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
os.environ["GITHUB_TOKEN"] = "fake-token-for-ui-test"
os.environ["OPENROUTER_API_KEY"] = "fake-key-for-ui-test"

from nicegui import app  # noqa: E402

from core.github_client import GitHubClient  # noqa: E402
from core.sandbox.runner import UnavailableRunner  # noqa: E402
from core.services import AppServices  # noqa: E402
from core.providers.base import ModelInfo  # noqa: E402
from tests.fixtures.pr_fixture import GOOD_REVIEW, GOOD_TEST, FakeProvider, make_gh  # noqa: E402

_MODELS = [ModelInfo(id="qwen/qwen3-coder-next:free", context_length=262144, is_free=True, recommended=True),
           ModelInfo(id="cohere/north-mini-code:free", context_length=256000, is_free=True, recommended=True),
           ModelInfo(id="qwen/qwen3.8-27b:free", context_length=262144, is_free=True, recommended=True),
           ModelInfo(id="google/gemma-4-31b-it:free", context_length=262144, is_free=True)]
FakeProvider.review_models = lambda self, force=False: _MODELS
FakeProvider.list_models = lambda self: [ModelInfo(id="qwen3-coder:30b", is_free=True)]

SUMMARY = {"summary": "Final summary of the discount change.", "overall_risk": "medium", "issues": []}
gh, pull = make_gh()
from datetime import datetime, timezone  # noqa: E402
from types import SimpleNamespace as _NS  # noqa: E402

gh.repo.pushed_at = datetime(2026, 9, 1, tzinfo=timezone.utc)
gh.repo.get_pulls = lambda state="open", sort="updated", direction="desc": [_NS(
    number=7, title=pull.title, user=pull.user, html_url=pull.html_url, head=pull.head,
    updated_at=datetime(2026, 9, 2, tzinfo=timezone.utc), draft=False)]
AppServices.github = lambda self: GitHubClient("t", gh=gh)
AppServices.provider = lambda self, provider=None, model=None: FakeProvider([GOOD_REVIEW, SUMMARY, GOOD_TEST], model=model or "fake-model")
AppServices.sandbox = lambda self: UnavailableRunner()

# Code reviewer: branch + archive for the fake repository
import io as _io  # noqa: E402
import zipfile as _zf  # noqa: E402

from tests.fixtures.pr_fixture import FAKE_TOKEN, ORDERS_SRC  # noqa: E402

gh.repo.get_branch = lambda b: _NS(commit=_NS(sha="c" * 40))
gh.repo.get_branches = lambda: [_NS(name="main"), _NS(name="feature/discount")]


def _archive(self, ref, sha, max_bytes=0):
    buf = _io.BytesIO()
    with _zf.ZipFile(buf, "w") as z:
        z.writestr("acme-shop-c0ffee/app/orders.py", ORDERS_SRC)
        z.writestr("acme-shop-c0ffee/app/auth.py", f'API_TOKEN = "{FAKE_TOKEN}"\ndef login(u, p):\n    return True\n')
        z.writestr("acme-shop-c0ffee/README.md", "# Shop\n")
    return buf.getvalue()


GitHubClient.download_archive = _archive


@app.get("/__test/push")
def push():
    pull.head.sha = "n" * 40
    return {"ok": True}


@app.get("/__test/posted")
def posted():
    return [{"event": r["event"], "n_comments": len(r["comments"] or []), "body": r["body"]} for r in pull.reviews]


if __name__ == "__main__":
    from dashboard.app import run_app
    run_app(native=False, port=int(sys.argv[1]), show=False)
