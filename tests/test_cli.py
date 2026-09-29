import json
import subprocess
import sys
from pathlib import Path

import pytest

import review_agent
from core.github_client import GitHubClient
from core.schemas import ReviewResult
from core.services import AppServices
from tests.fixtures.pr_fixture import GOOD_REVIEW, GOOD_TEST, FakeProvider, make_gh

URL = "https://github.com/acme/shop/pull/7"
SUMMARY = {"summary": "Final.", "overall_risk": "medium", "issues": []}
ROOT = Path(__file__).resolve().parent.parent


@pytest.fixture
def wired(monkeypatch):
    gh, pull = make_gh()
    seen = {}
    monkeypatch.setattr(AppServices, "github", lambda self: GitHubClient("t", gh=gh))

    def provider(self, provider=None, model=None):
        seen.update(provider=provider, model=model)
        return FakeProvider([GOOD_REVIEW, SUMMARY, GOOD_TEST], model=model or "fake-model")

    monkeypatch.setattr(AppServices, "provider", provider)
    return pull, seen


def test_no_arguments_prints_help(capsys):
    assert review_agent.main([]) == 0
    out = capsys.readouterr().out
    assert "usage:" in out and "--dry-run" in out and "--post" in out and "--json" in out


def test_help_via_real_process():
    p = subprocess.run([sys.executable, str(ROOT / "review_agent.py")], capture_output=True, text=True, cwd=ROOT)
    assert p.returncode == 0 and "--generate-tests" in p.stdout and "--provider" in p.stdout


@pytest.mark.parametrize("url", ["https://example.com/a/b/pull/1", "nonsense", "https://github.com/a/b/issues/3"])
def test_invalid_url_exit_code_2(url, capsys):
    assert review_agent.main([url]) == 2
    assert "error:" in capsys.readouterr().err


def test_dry_run_is_default_and_publishes_nothing(wired, capsys):
    pull, _ = wired
    assert review_agent.main([URL]) == 0
    cap = capsys.readouterr()
    assert "ZeroPulse PR Review Report" in cap.out and "nothing was published" in cap.err
    assert pull.reviews == []
    assert review_agent.main([URL, "--dry-run"]) == 0 and pull.reviews == []


def test_json_output_is_valid_schema_on_stdout_only(wired, capsys):
    assert review_agent.main([URL, "--json", "--generate-tests"]) == 0
    cap = capsys.readouterr()
    result = ReviewResult.model_validate(json.loads(cap.out))
    assert result.issues and result.test_file and result.metadata.head_sha == "h" * 40
    assert "Analyzing" in cap.err  # progress goes to stderr and never corrupts the JSON


def test_generate_tests_flag_controls_test_generation(wired, monkeypatch, capsys):
    monkeypatch.setattr(AppServices, "provider", lambda self, provider=None, model=None: FakeProvider([GOOD_REVIEW, SUMMARY]))
    assert review_agent.main([URL, "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["test_file"] is None


def test_output_file_and_model_provider_plumbing(wired, tmp_path, capsys):
    _, seen = wired
    out = tmp_path / "r.md"
    assert review_agent.main([URL, "--output", str(out), "--model", "google/gemma-3-27b-it:free", "--provider", "openrouter"]) == 0
    assert seen == {"provider": "openrouter", "model": "google/gemma-3-27b-it:free"}
    text = out.read_text(encoding="utf-8")
    assert text.startswith("# ZeroPulse PR Review Report")
    assert "google/gemma-3-27b-it:free" in text
    assert capsys.readouterr().out == ""  # with --output and no --json, stdout stays quiet


def test_post_is_explicit_and_posts_one_comment_review(wired, capsys):
    pull, _ = wired
    assert review_agent.main([URL, "--post"]) == 0
    assert len(pull.reviews) == 1 and pull.reviews[0]["event"] == "COMMENT"
    assert "published:" in capsys.readouterr().err
    assert review_agent.main([URL]) == 0 and len(pull.reviews) == 1  # a later default run posts nothing more


def test_post_and_dry_run_are_mutually_exclusive():
    with pytest.raises(SystemExit) as e:
        review_agent.main([URL, "--dry-run", "--post"])
    assert e.value.code == 2


def test_post_blocked_when_pr_moved(wired, monkeypatch, capsys):
    pull, _ = wired
    orig = AppServices.publisher

    def moving(self):
        pull.head.sha = "m" * 40  # author pushes between review and publish
        return orig(self)

    monkeypatch.setattr(AppServices, "publisher", moving)
    assert review_agent.main([URL, "--post"]) == 1
    assert pull.reviews == [] and "changed after this review" in capsys.readouterr().err


def test_private_repo_consent_exit_code(monkeypatch, capsys):
    gh, pull = make_gh(private=True)
    monkeypatch.setattr(AppServices, "github", lambda self: GitHubClient("t", gh=gh))
    monkeypatch.setattr(AppServices, "provider", lambda self, provider=None, model=None: FakeProvider([GOOD_REVIEW]))
    assert review_agent.main([URL]) == 3
    assert "private" in capsys.readouterr().err
    monkeypatch.setattr(AppServices, "provider", lambda self, provider=None, model=None: FakeProvider([GOOD_REVIEW, SUMMARY]))
    assert review_agent.main([URL, "--allow-private-hosted"]) == 0


def test_runtime_errors_are_reported_not_hidden(monkeypatch, capsys):
    from core.providers import ProviderError
    gh, _ = make_gh()
    monkeypatch.setattr(AppServices, "github", lambda self: GitHubClient("t", gh=gh))
    monkeypatch.setattr(AppServices, "provider", lambda self, provider=None, model=None: FakeProvider([ProviderError("auth", "Invalid key")]))
    assert review_agent.main([URL]) == 1
    assert "Invalid key" in capsys.readouterr().err
