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
from tests.fixtures.pr_fixture import GOOD_REVIEW, GOOD_TEST, FakeProvider, make_gh  # noqa: E402

SUMMARY = {"summary": "Final summary of the discount change.", "overall_risk": "medium", "issues": []}
gh, pull = make_gh()
AppServices.github = lambda self: GitHubClient("t", gh=gh)
AppServices.provider = lambda self, provider=None, model=None: FakeProvider([GOOD_REVIEW, SUMMARY, GOOD_TEST], model=model or "fake-model")
AppServices.sandbox = lambda self: UnavailableRunner()


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
