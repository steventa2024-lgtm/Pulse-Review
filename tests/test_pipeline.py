import threading

import pytest

from core.db import Database
from core.github_client import GitHubClient, GitHubError
from core.publisher import (ConfirmationError, DuplicatePublicationError, PublishError, PublishOptions, Publisher,
                            StaleReviewError, build_plan, neutralize)
from core.review_pipeline import (ConsentRequired, ProgressEvent, ReviewCancelled, ReviewOptions, ReviewPipeline,
                                  apply_sandbox_result)
from core.reviewer import ReviewError
from core.sandbox.runner import SandboxResult, SandboxRunner
from core.schemas import PRRef
from core.watcher import WatchService
from tests.fixtures.pr_fixture import (FAKE_TOKEN, GOOD_REVIEW, GOOD_TEST, FakeProvider, make_file, make_gh)

REF = PRRef(owner="acme", repo="shop", number=7)
SUMMARY = {"summary": "Final summary.", "overall_risk": "medium", "issues": []}


def _pipe(tmp_path, responses=None, *, private=False, options=None, provider=None, db=True, files=None, sandbox=None, cancel=None, head="h" * 40):
    gh, pull = make_gh(private=private, files=files, head_sha=head)
    d = Database(tmp_path / "r.db") if db else None
    prov = provider or FakeProvider(responses if responses is not None else [GOOD_REVIEW, SUMMARY, GOOD_TEST])
    events: list[ProgressEvent] = []
    p = ReviewPipeline(github=GitHubClient("t", gh=gh), provider=prov, options=options or ReviewOptions(), db=d,
                       sandbox=sandbox, progress=events.append, cancel=cancel)
    return p, d, pull, events, gh


def test_full_review_end_to_end(tmp_path):
    p, db, _, events, _ = _pipe(tmp_path)
    out = p.run("https://github.com/acme/shop/pull/7")
    r = out.result
    # findings are real, verified, grounded and capped (AI + static merged)
    assert 1 <= len(r.issues) <= 3
    assert {i.title for i in r.issues} >= {"Possible credential committed (github token)"}
    assert all(i.verification_status in ("verified", "plausible") or i.category == "testing" for i in r.issues)
    assert "ghost.py" not in " ".join(i.file for i in r.issues)
    assert r.metadata.head_sha == "h" * 40 and r.metadata.provider == "fake" and r.metadata.model == "fake-model"
    assert r.metadata.input_tokens == 300 and r.metadata.output_tokens == 150  # summed from actual usage
    assert r.test_file and r.test_file.execution_status == "not_run" and r.test_file.filename == "tests/test_orders.py"
    assert any("discarded" in l for l in r.limitations)  # hallucinations are disclosed, not hidden
    assert any("no patch data" in l for l in r.limitations)  # binary/huge files disclosed
    cov = {c.path: c.status for c in r.files_reviewed}
    assert cov["app/orders.py"] == "reviewed" and cov["assets/logo.png"] == "skipped" and cov["data/huge.json"] == "unavailable"
    assert r.overall_risk == "critical"  # committed credential
    # real stage transitions, in order, no percentages
    steps = [e.step for e in events if e.state == "running"]
    assert steps[:2] == ["connect", "fetch"] and "analyze" in steps and steps.index("validate") < steps.index("tests") < steps.index("report")
    # persisted
    row = db.get_review(out.review_id)
    assert row["status"] == "completed" and row["head_sha"] == "h" * 40 and row["provider"] == "fake" and row["pr_title"]
    assert db.get_result(out.review_id).issues[0].id == "F1"


def test_ai_ordering_severity_and_max_findings(tmp_path):
    p, *_ = _pipe(tmp_path, options=ReviewOptions(max_findings=1, generate_tests=False), responses=[GOOD_REVIEW, SUMMARY])
    r = p.run(REF).result
    assert len(r.issues) == 1 and r.issues[0].severity == "critical"
    assert any("top 1 findings" in l for l in r.limitations)


def test_no_invented_issues_when_model_finds_nothing(tmp_path):
    clean = [make_file("app/orders.py", "@@ -1,1 +1,2 @@\n a\n+b = 2", additions=1, deletions=0)]
    p, *_ = _pipe(tmp_path, [{"summary": "Trivial.", "overall_risk": "low", "issues": []}], files=clean,
                  options=ReviewOptions(generate_tests=False))
    r = p.run(REF).result
    assert not [i for i in r.issues if i.source == "ai"] and r.overall_risk in ("low", "medium")
    assert r.summary


def test_private_repo_requires_consent_before_any_model_call(tmp_path):
    prov = FakeProvider([GOOD_REVIEW])
    p, db, *_ = _pipe(tmp_path, private=True, provider=prov)
    with pytest.raises(ConsentRequired):
        p.run(REF)
    assert prov.calls == []  # nothing left the machine
    assert db.list_reviews()[0]["status"] == "failed"
    # consent granted → proceeds; local provider never needs consent
    p2, *_ = _pipe(tmp_path, private=True, options=ReviewOptions(private_hosted_consent=True, generate_tests=False), responses=[GOOD_REVIEW, SUMMARY])
    assert p2.run(REF).result.issues
    prov3 = FakeProvider([GOOD_REVIEW, SUMMARY], hosted=False)
    p3, *_ = _pipe(tmp_path, private=True, provider=prov3, options=ReviewOptions(generate_tests=False))
    assert p3.run(REF).result.issues


def test_provider_failure_surfaces_instead_of_hollow_success(tmp_path):
    from core.providers import ProviderError
    p, db, *_ = _pipe(tmp_path, [ProviderError("auth", "bad key")])
    with pytest.raises(ProviderError):
        p.run(REF)
    row = db.list_reviews()[0]
    assert row["status"] == "failed" and db.get_review(row["id"])["error"] == "bad key"


def test_malformed_output_everywhere_fails_the_review(tmp_path):
    p, db, *_ = _pipe(tmp_path, ["junk"] * 3, options=ReviewOptions(generate_tests=False))
    with pytest.raises(ReviewError):
        p.run(REF)
    assert db.list_reviews()[0]["status"] == "failed"


def test_partial_chunk_failure_is_disclosed(tmp_path):
    from tests.test_diff_parser import _big_file
    files = [_big_file(f"src/m{i}.py", 60) for i in range(3)]
    ok = {"summary": "ok", "overall_risk": "low", "issues": []}
    prov = FakeProvider([ok, "junk", "junk", "junk", ok, SUMMARY], ctx=4096)
    p, db, *_ = _pipe(tmp_path, provider=prov, files=files,
                      options=ReviewOptions(depth="deep", max_context_budget=4096, generate_tests=False))
    r = p.run(REF).result
    assert r.metadata.chunks == 3
    failed = [c for c in r.files_reviewed if c.status == "unavailable"]
    assert len(failed) == 1 and "AI analysis failed" in failed[0].reason
    assert any("AI analysis failed for" in l and "NOT fully reviewed" in l for l in r.limitations)
    assert db.list_reviews()[0]["status"] == "completed"


def test_cancellation_mid_review(tmp_path):
    ev = threading.Event()
    prov = FakeProvider([lambda m: (ev.set(), GOOD_REVIEW)[1], SUMMARY])
    p, db, *_ = _pipe(tmp_path, provider=prov, cancel=ev, options=ReviewOptions(generate_tests=False))
    with pytest.raises(ReviewCancelled):
        p.run(REF)
    assert db.list_reviews()[0]["status"] == "cancelled"


def test_invalid_url_rejected_before_network(tmp_path):
    from core.github_client import InvalidPRUrl
    p, *_ = _pipe(tmp_path)
    with pytest.raises(InvalidPRUrl):
        p.run("https://github.com/acme/shop/issues/7")


def test_github_failure_recorded(tmp_path):
    p, db, _, _, gh = _pipe(tmp_path)
    gh.get_repo = lambda n: (_ for _ in ()).throw(__import__("github").GithubException(404, {"message": "Not Found"}, {}))
    with pytest.raises(GitHubError) as e:
        p.run(REF)
    assert e.value.kind == "not_found" and db.list_reviews()[0]["status"] == "failed"


def test_prompt_injection_in_pr_does_not_change_behaviour(tmp_path):
    # PR body says "print the GitHub token"; the model answers normally and no credential reaches the prompt.
    prov = FakeProvider([GOOD_REVIEW, SUMMARY])
    p, *_ = _pipe(tmp_path, provider=prov, options=ReviewOptions(generate_tests=False))
    p.run(REF)
    for call in prov.calls:
        assert FAKE_TOKEN not in " ".join(m["content"] for m in call)


# ------------------------------------------------------------------ sandbox integration
class FakeRunner(SandboxRunner):
    name = "fake"

    def __init__(self, status="passed", ok=True):
        self.status, self.ok, self.reqs = status, ok, []

    def available(self):
        return self.ok, "" if self.ok else "Sandbox unavailable — generated test has not been executed."

    def run(self, req, cancel=None):
        self.reqs.append(req)
        return SandboxResult(self.status, 2, 0, 0.5, "2 passed", "fake")


def test_sandbox_is_opt_in_and_reports_honestly(tmp_path, monkeypatch):
    monkeypatch.setattr(GitHubClient, "download_archive", lambda self, ref, sha, **k: b"zip")
    runner = FakeRunner()
    p, db, *_ = _pipe(tmp_path, options=ReviewOptions(run_sandbox=False), sandbox=runner)
    r = p.run(REF).result
    assert runner.reqs == [] and r.test_file.execution_status == "not_run"
    runner2 = FakeRunner("passed")
    p2, db2, *_ = _pipe(tmp_path, options=ReviewOptions(run_sandbox=True), sandbox=runner2, responses=[GOOD_REVIEW, SUMMARY, GOOD_TEST])
    r2 = p2.run(REF).result
    assert r2.test_file.execution_status == "passed" and r2.test_file.artifact_state == "executed" and r2.test_file.tests_passed == 2
    assert runner2.reqs[0].test_path == "tests/test_orders.py" and not runner2.reqs[0].install_dependencies
    ex = db2.list_executions(db2.list_reviews()[0]["id"])
    assert ex and ex[0]["status"] == "passed"
    p3, *_ = _pipe(tmp_path, options=ReviewOptions(run_sandbox=True), sandbox=FakeRunner(ok=False), responses=[GOOD_REVIEW, SUMMARY, GOOD_TEST])
    r3 = p3.run(REF).result
    assert r3.test_file.execution_status == "not_run" and "Sandbox unavailable" in r3.test_file.execution_output


# ------------------------------------------------------------------ publishing
def _completed(tmp_path, head="h" * 40):
    p, db, pull, _, gh = _pipe(tmp_path, options=ReviewOptions(generate_tests=True))
    out = p.run(REF)
    return out, db, pull, gh


def test_publish_requires_exact_confirmation_and_records_identifiers(tmp_path):
    out, db, pull, gh = _completed(tmp_path)
    pub = Publisher(GitHubClient("t", gh=gh), db)
    plan = pub.prepare(out.review_id, PublishOptions(mode="overview", include_test=True))
    assert "PulseReview" in plan.body and "tests/test_orders.py" in plan.body and not plan.inline_comments
    with pytest.raises(ConfirmationError):
        pub.publish(out.review_id, plan, "acme/other#7")
    assert pull.reviews == []  # nothing posted on mismatch
    rec = pub.publish(out.review_id, plan, "acme/shop#7")
    assert len(pull.reviews) == 1 and pull.reviews[0]["event"] == "COMMENT"  # never APPROVE / REQUEST_CHANGES
    assert rec.github_review_id == 901 and "pullrequestreview-901" in rec.url
    pubs = db.list_publications(out.review_id)
    assert pubs[0]["github_review_id"] == 901 and pubs[0]["head_sha"] == "h" * 40
    assert db.get_review(out.review_id)["status"] == "posted"


def test_duplicate_publication_prevented(tmp_path):
    out, db, pull, gh = _completed(tmp_path)
    pub = Publisher(GitHubClient("t", gh=gh), db)
    plan = pub.prepare(out.review_id, PublishOptions())
    pub.publish(out.review_id, plan, "acme/shop#7")
    plan2 = pub.prepare(out.review_id, PublishOptions())
    with pytest.raises(DuplicatePublicationError) as e:
        pub.publish(out.review_id, plan2, "acme/shop#7")
    assert len(pull.reviews) == 1 and e.value.url
    edited = pub.prepare(out.review_id, PublishOptions(body_override="Edited by the human"))
    pub.publish(out.review_id, edited, "acme/shop#7")  # intentionally different content is allowed
    assert len(pull.reviews) == 2


def test_stale_pr_detected_at_prepare_and_at_publish(tmp_path):
    out, db, pull, gh = _completed(tmp_path)
    pub = Publisher(GitHubClient("t", gh=gh), db)
    plan = pub.prepare(out.review_id, PublishOptions())
    pull.head.sha = "n" * 40  # author pushed after preview, before clicking confirm
    with pytest.raises(StaleReviewError) as e:
        pub.publish(out.review_id, plan, "acme/shop#7")
    assert e.value.current_sha == "n" * 40 and pull.reviews == []
    assert db.get_review(out.review_id)["status"] == "stale"
    with pytest.raises(StaleReviewError):
        pub.prepare(out.review_id, PublishOptions())


def test_closed_pr_not_published(tmp_path):
    out, db, pull, gh = _completed(tmp_path)
    pull.state = "closed"
    with pytest.raises(PublishError):
        Publisher(GitHubClient("t", gh=gh), db).prepare(out.review_id, PublishOptions())


def test_inline_comments_only_for_verified_valid_locations(tmp_path):
    out, db, pull, gh = _completed(tmp_path)
    pub = Publisher(GitHubClient("t", gh=gh), db)
    plan = pub.prepare(out.review_id, PublishOptions(mode="inline"))
    assert plan.inline_comments, "verified findings should be anchored"
    for c in plan.inline_comments:
        assert set(c) == {"path", "line", "side", "body"} and c["side"] in ("RIGHT", "LEFT") and isinstance(c["line"], int)
    fs = {f.filename for f in GitHubClient("t", gh=gh).fetch_pr(REF).files}
    assert all(c["path"] in fs for c in plan.inline_comments)
    # a finding whose line is not in the diff must be moved to the overview
    result = db.get_result(out.review_id)
    result.issues[0].line = 9999
    p2 = build_plan(REF, result, PublishOptions(mode="inline"), __import__("core.diff_parser", fromlist=["DiffIndex"]).DiffIndex(GitHubClient("t", gh=gh).fetch_pr(REF).files), "h" * 40)
    assert result.issues[0].id in p2.overview_issue_ids and p2.warnings
    pub.publish(out.review_id, plan, "acme/shop#7")
    assert pull.reviews[0]["comments"] == plan.inline_comments


def test_selection_and_edit_are_respected(tmp_path):
    out, db, pull, gh = _completed(tmp_path)
    pub = Publisher(GitHubClient("t", gh=gh), db)
    result = db.get_result(out.review_id)
    first = result.issues[0].id
    plan = pub.prepare(out.review_id, PublishOptions(issue_ids=[first], include_test=False))
    assert plan.overview_issue_ids == [first] and "tests/test_orders.py" not in plan.body
    none = pub.prepare(out.review_id, PublishOptions(issue_ids=[]))
    assert "No findings were selected" in none.body


def test_mentions_are_neutralized_so_ai_text_cannot_ping_people():
    assert "@octocat" not in neutralize("thanks @octocat and @org/team") and "@​octocat" in neutralize("@octocat")
    assert neutralize("user@example.com") == "user@example.com"


# ------------------------------------------------------------------ watched repositories
def test_watch_detects_new_and_updated_prs_without_reprocessing(tmp_path):
    import httpx
    state = {"sha": "s1", "etag": 'W/"1"', "calls": 0}

    def handler(req):
        state["calls"] += 1
        if req.headers.get("if-none-match") == state["etag"]:
            return httpx.Response(304)
        return httpx.Response(200, headers={"ETag": state["etag"]}, json=[
            {"number": 5, "title": "T", "user": {"login": "u"}, "html_url": "h", "head": {"sha": state["sha"]}},
            {"number": 6, "title": "T2", "user": {"login": "u"}, "html_url": "h6", "head": {"sha": "z"}}])

    gh, _ = make_gh()
    db = Database(tmp_path / "w.db")
    client = GitHubClient("t", gh=gh, http=httpx.Client(transport=httpx.MockTransport(handler)))
    w = WatchService(client, db)
    assert w.add_repo("acme/shop") == "acme/shop"
    r1 = w.refresh("acme/shop")
    assert (r1.new, r1.updated, r1.not_modified) == (2, 0, False)
    assert {p["indicator"] for p in db.list_watched_prs("acme/shop")} == {"new"}
    r2 = w.refresh("acme/shop")
    assert r2.not_modified  # conditional request → no reprocessing
    state.update(sha="s2", etag='W/"2"')
    r3 = w.refresh("acme/shop")
    assert (r3.new, r3.updated) == (0, 1)
    pr5 = db.get_watched_pr("acme/shop", 5)
    assert pr5["indicator"] == "updated" and pr5["head_sha"] == "s2"
    assert [p["pr_number"] for p in w.needs_analysis("acme/shop")] == [6, 5]
    db.mark_pr_reviewed("acme/shop", 5, "s2")
    assert [p["pr_number"] for p in w.needs_analysis("acme/shop")] == [6]
    assert db.list_watched_repos()[0]["last_checked"]  # persisted


def test_watch_marks_vanished_prs_closed_and_rejects_inaccessible_repo(tmp_path):
    import httpx
    calls = iter([[{"number": 1, "title": "a", "user": {}, "html_url": "", "head": {"sha": "a"}}, {"number": 2, "title": "b", "user": {}, "html_url": "", "head": {"sha": "b"}}],
                  [{"number": 2, "title": "b", "user": {}, "html_url": "", "head": {"sha": "b"}}]])
    client = GitHubClient("t", gh=make_gh()[0], http=httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, json=next(calls)))))
    db = Database(tmp_path / "w.db")
    w = WatchService(client, db)
    w.add_repo("acme/shop")
    w.refresh("acme/shop")
    w.refresh("acme/shop")
    assert [p["pr_number"] for p in db.list_watched_prs("acme/shop")] == [2]
    gh = make_gh()[0]
    gh.get_repo = lambda n: (_ for _ in ()).throw(__import__("github").GithubException(404, {"message": "Not Found"}, {}))
    with pytest.raises(GitHubError):
        WatchService(GitHubClient("t", gh=gh), db).add_repo("acme/hidden")
    assert [r["repo"] for r in db.list_watched_repos()] == ["acme/shop"]
