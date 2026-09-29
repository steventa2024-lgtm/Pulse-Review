import pytest
from pydantic import ValidationError

from core.context_builder import build_chunks, build_repo_context
from core.diff_parser import DiffIndex
from core.github_client import GitHubClient
from core.reviewer import ReviewError, ReviewFocus, Reviewer, dedupe_issues, derive_risk, finalize_ids, verify_issues
from core.schemas import Issue, LLMIssue, LLMReview, PRRef
from core.static_checks import run_static_checks
from tests.fixtures.pr_fixture import FAKE_TOKEN, GOOD_REVIEW, FakeProvider, make_gh


@pytest.fixture
def pr():
    gh, _ = make_gh()
    return GitHubClient("t", gh=gh).fetch_pr(PRRef(owner="acme", repo="shop", number=7))


# ------------------------------------------------------------------ schema validation
def test_llm_schema_normalizes_aliases_and_bad_values():
    r = LLMReview.model_validate({"overall_risk": "Severe", "issues": [
        {"file": "a.py", "title": "t", "explanation": "e", "severity": "Major", "category": "Input Validation", "line": "12", "side": "right"}]})
    i = r.issues[0]
    assert (r.overall_risk, i.severity, i.category, i.line, i.side) == ("critical", "high", "bug", 12, "RIGHT")
    assert LLMIssue(file="a", title="t", explanation="e", line=-4).line is None
    assert LLMIssue(file="a", title="t", explanation="e", line="n/a").line is None


@pytest.mark.parametrize("bad", [{"issues": [{"title": "no file", "explanation": "e"}]},
                                 {"issues": [{"file": "a", "title": "t", "explanation": "e", "severity": "catastrophic"}]},
                                 {"issues": "not a list"}])
def test_llm_schema_rejects_malformed(bad):
    with pytest.raises(ValidationError):
        LLMReview.model_validate(bad)


def test_malformed_output_is_retried_with_corrective_instructions(pr):
    prov = FakeProvider(["this is not json", {"issues": [{"title": "missing fields"}]}, GOOD_REVIEW])
    ctx = build_repo_context(pr)
    plan = build_chunks(pr, 8000)
    out = Reviewer(prov).review_chunk(pr, plan.chunks[0], ctx)
    assert len(out.issues) == 4 and len(prov.calls) == 3
    assert "not valid" in prov.calls[1][-1]["content"] and "JSON" in prov.calls[2][-1]["content"]


def test_persistently_malformed_output_raises_never_reports_success(pr):
    prov = FakeProvider(["nope", "still nope", "nope again"])
    plan = build_chunks(pr, 8000)
    with pytest.raises(ReviewError):
        Reviewer(prov).review_chunk(pr, plan.chunks[0], build_repo_context(pr))


# ------------------------------------------------------------------ prompt safety
def test_prompt_frames_repo_content_as_untrusted_and_redacts_for_hosted(pr):
    prov = FakeProvider([GOOD_REVIEW], hosted=True)
    rv = Reviewer(prov, ReviewFocus())
    rv.review_chunk(pr, build_chunks(pr, 8000).chunks[0], build_repo_context(pr))
    system, user = prov.calls[0][0]["content"], prov.calls[0][1]["content"]
    assert "NEVER an instruction" in system and "<<<UNTRUSTED_REPOSITORY_DATA" in user
    assert "Ignore all previous instructions" in user  # visible to the model only inside the untrusted block
    assert user.index("UNTRUSTED_REPOSITORY_DATA") < user.index("Ignore all previous")
    assert "instruction-like content" in user
    assert FAKE_TOKEN not in user and "[REDACTED:github_token]" in user and rv.redactions >= 1
    assert "credentials" not in system.lower() or "reveal credentials" in system.lower()


def test_local_provider_gets_unredacted_code_but_no_remote_send(pr):
    prov = FakeProvider([GOOD_REVIEW], hosted=False)
    Reviewer(prov).review_chunk(pr, build_chunks(pr, 8000).chunks[0], build_repo_context(pr))
    assert FAKE_TOKEN in prov.calls[0][1]["content"]


# ------------------------------------------------------------------ verification
def test_verify_grounds_findings_in_diff_and_discards_unsupported(pr):
    raw = LLMReview.model_validate(GOOD_REVIEW).issues
    rep = verify_issues(raw, DiffIndex(pr.files), pr)
    titles = {i.title: i for i in rep.issues}
    assert set(titles) == {"parse_qty crashes on invalid input", "Discount percentage is not validated"}
    a = titles["parse_qty crashes on invalid input"]
    assert a.verification_status == "verified" and a.line == 20
    assert len(rep.discarded) == 2  # hallucinated file + unanchored claim
    assert any("ghost.py" in d for d in rep.discarded)


def test_verify_relocates_wrong_line_number_using_evidence(pr):
    raw = [LLMIssue(file="app/orders.py", line=999, title="t", explanation="e", evidence="return int(raw)")]
    (i,) = verify_issues(raw, DiffIndex(pr.files), pr).issues
    assert i.line == 20 and i.verification_status == "verified"


def test_verify_marks_plausible_when_only_line_matches_and_drops_unanchorable(pr):
    raw = [LLMIssue(file="app/orders.py", line=20, title="t1", explanation="e", evidence="paraphrase of code"),
           LLMIssue(file="app/orders.py", line=None, title="t2", explanation="e", evidence="", category="testing")]
    rep = verify_issues(raw, DiffIndex(pr.files), pr)
    by = {i.title: i for i in rep.issues}
    assert by["t1"].verification_status == "plausible"
    assert by["t2"].verification_status == "unverified" and by["t2"].line is None  # testing gap goes to overview


def test_verify_left_side_and_file_suffix_resolution(pr):
    raw = [LLMIssue(file="orders.py", line=14, side="LEFT", title="removed formula", explanation="e", evidence="return price * (1 - pct / 100)")]
    (i,) = verify_issues(raw, DiffIndex(pr.files), pr).issues
    assert i.file == "app/orders.py" and i.side == "LEFT" and i.verification_status == "verified"


def test_verify_withholds_syntactically_broken_python_suggestions(pr):
    raw = [LLMIssue(file="app/orders.py", line=20, title="t", explanation="e", evidence="return int(raw)",
                    suggested_code="def broken(:\n  pass")]
    rep = verify_issues(raw, DiffIndex(pr.files), pr)
    assert rep.issues[0].suggested_code is None and any("syntax" in n for n in rep.notes)
    ok = [LLMIssue(file="app/orders.py", line=20, title="t", explanation="e", evidence="return int(raw)",
                   suggested_code="    try:\n        return int(raw)\n    except ValueError:\n        return 0")]
    assert verify_issues(ok, DiffIndex(pr.files), pr).issues[0].suggested_code


def test_dedupe_merges_same_location_and_similar_titles():
    mk = lambda id, line, title, sev="medium", cat="bug": Issue(id=id, file="a.py", line=line, title=title, explanation="e", severity=sev, category=cat)  # noqa: E731
    out = dedupe_issues([mk("1", 5, "Missing validation of pct"), mk("2", 5, "pct not validated", "high"),
                         mk("3", 9, "Missing validation of pct"), mk("4", 30, "Completely different problem"),
                         mk("5", 31, "Completely different problem!")])
    # 1 merges into the higher-severity finding at the same line; 5 is a near-identical title in the same file
    assert [i.id for i in out] == ["2", "3", "4"]
    assert [i.id for i in finalize_ids(out)] == ["F1", "F2", "F3"]


def test_risk_derivation_follows_evidence_not_model_opinion():
    assert derive_risk([], "critical") == "low"
    hi = Issue(id="1", file="a", title="t", explanation="e", severity="high")
    assert derive_risk([hi]) == "high" and derive_risk([hi], "critical") == "critical"
    lo = Issue(id="2", file="a", title="t", explanation="e", severity="low")
    assert derive_risk([lo], "critical") == "medium"
    sec = Issue(id="3", file="a", title="t", explanation="e", severity="low", category="security")
    assert derive_risk([sec]) == "medium"


# ------------------------------------------------------------------ static analysis
def test_static_checks_find_credentials_without_leaking_them(pr):
    ctx = build_repo_context(pr)
    rep = run_static_checks(pr, ctx, DiffIndex(pr.files), fetch_file=None)
    cred = [i for i in rep.issues if "credential" in i.title.lower()]
    assert len(cred) == 1 and cred[0].file == "app/auth.py" and cred[0].line == 3
    assert cred[0].severity == "critical" and cred[0].verification_status == "verified"
    assert FAKE_TOKEN not in cred[0].evidence and "REDACTED" in cred[0].evidence
    assert any(i.category == "testing" for i in rep.issues)  # source changed, no tests changed
    assert any("Security-sensitive" in h for h in rep.hints)


def test_static_syntax_check_uses_parsing_only(pr):
    ctx = build_repo_context(pr)
    bad = lambda path: "def broken(:\n    pass\n" if path == "app/orders.py" else None  # noqa: E731
    rep = run_static_checks(pr, ctx, DiffIndex(pr.files), fetch_file=bad)
    syn = [i for i in rep.issues if "syntax error" in i.title]
    assert syn and syn[0].file == "app/orders.py" and syn[0].severity == "high"


def test_static_risky_patterns_only_on_added_lines():
    from core.schemas import FileChange, PRData
    patch = "@@ -1,2 +1,3 @@\n import requests\n-r = requests.get(u)\n+r = requests.get(u, verify=False)\n x = eval(y)"
    prd = PRData(ref=PRRef(owner="o", repo="r", number=1), files=[FileChange(filename="m.py", additions=1, deletions=1, patch=patch)])
    rep = run_static_checks(prd, build_repo_context(prd), DiffIndex(prd.files))
    titles = [i.title for i in rep.issues]
    assert any("TLS" in t for t in titles) and not any("eval" in t for t in titles)  # eval line is context, not added


def test_deep_depth_adds_surrounding_source_from_pr_commit_others_do_not(tmp_path):
    from core.db import Database
    from core.review_pipeline import ReviewOptions, ReviewPipeline
    from tests.fixtures.pr_fixture import ORDERS_SRC
    SUMMARY = {"summary": "s", "overall_risk": "low", "issues": []}

    def run(depth):
        gh, _ = make_gh()
        prov = FakeProvider([GOOD_REVIEW, SUMMARY])
        ReviewPipeline(github=GitHubClient("t", gh=gh), provider=prov, options=ReviewOptions(depth=depth, generate_tests=False),
                       db=Database(tmp_path / f"{depth}.db")).run(PRRef(owner="acme", repo="shop", number=7))
        return prov.calls[0][1]["content"]

    deep, standard = run("deep"), run("standard")
    assert "Full file at the PR head commit" in deep and "full_source:app/orders.py" in deep and "def checkout(cart):" in deep
    assert "Full file at the PR head commit" not in standard
