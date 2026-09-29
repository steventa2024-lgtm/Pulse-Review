import io
import zipfile
from types import SimpleNamespace as NS

import httpx
import pytest

from core.code_audit import (AuditOptions, CodeAuditPipeline, build_audit_chunks, in_scope, is_text_candidate,
                             read_zip_files, render_audit_report, scan_secrets, score_issues, verify_audit_issues)
from core.db import Database
from core.github_client import GitHubClient
from core.review_pipeline import ConsentRequired
from core.schemas import Issue, LLMIssue
from tests.fixtures.pr_fixture import FAKE_TOKEN, FakeProvider, make_gh

CART = '''def add_item(item, cart=[]):
    cart.append(item)
    return cart


def average_price(items):
    total = sum(i["price"] for i in items)
    return total / len(items)
'''
FILES = {
    "shop/cart.py": CART,
    "shop/config.py": f'API_TOKEN = "{FAKE_TOKEN}"\nDEBUG = True\n',
    "shop/util.py": "import subprocess\n\ndef run(cmd):\n    return subprocess.run(cmd, shell=True)\n",
    "tests/test_x.py": 'password = "example-password-123"\n',
    "README.md": "# Shop\n",
    "assets/logo.png": "\x00binary",
    "node_modules/lib/index.js": "var x = 1;",
}

AI = {"summary": "Cart helpers have edge-case bugs.", "overall_risk": "high", "issues": [
    {"severity": "high", "category": "bug", "file": "shop/cart.py", "line": 1, "title": "Mutable default argument",
     "explanation": "cart=[] is shared across calls.", "evidence": "def add_item(item, cart=[]):", "suggested_fix": "Use None."},
    {"severity": "medium", "category": "bug", "file": "shop/cart.py", "line": 99, "title": "Division by zero on empty cart",
     "explanation": "len(items) may be 0.", "evidence": "return total / len(items)"},
    {"severity": "high", "category": "security", "file": "shop/ghost.py", "line": 3, "title": "Hallucinated",
     "explanation": "not real", "evidence": "nope"},
]}
SUMMARY = {"summary": "Overall moderate risk; fix the leaked token first.", "overall_risk": "high", "issues": []}


def _zip(files, root="acme-shop-abc123"):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        for k, v in files.items():
            z.writestr(f"{root}/{k}", v)
    return buf.getvalue()


def _client(files=FILES, private=False):
    gh, _ = make_gh(private=private)
    gh.repo.get_branch = lambda b: NS(commit=NS(sha="c" * 40))
    http = httpx.Client(transport=httpx.MockTransport(lambda r: httpx.Response(200, content=_zip(files))))
    return GitHubClient("t", gh=gh, http=http)


def test_file_filters_and_scope():
    assert is_text_candidate("shop/cart.py") and is_text_candidate(".env") and is_text_candidate("config/app.yml")
    assert not is_text_candidate("node_modules/a/b.js") and not is_text_candidate("package-lock.json")
    assert not is_text_candidate("assets/logo.png")
    assert in_scope("shop/cart.py", "folder", "shop") and not in_scope("shopping/x.py", "folder", "shop")
    assert in_scope("a.py", "file", "a.py") and not in_scope("b.py", "file", "a.py") and in_scope("x", "repo", "")


def test_zip_reading_skips_binary_and_filters_in_memory():
    got = read_zip_files(_zip(FILES), lambda p: is_text_candidate(p), 100)
    assert "shop/cart.py" in got and "assets/logo.png" not in got and "node_modules/lib/index.js" not in got


def test_secret_scan_finds_leaks_without_exposing_them():
    issues = scan_secrets({"shop/config.py": FILES["shop/config.py"], "tests/test_x.py": FILES["tests/test_x.py"]})
    real = [i for i in issues if i.file == "shop/config.py"][0]
    assert real.severity == "critical" and real.category == "secrets" and real.line == 1 and real.verification_status == "verified"
    assert FAKE_TOKEN not in real.evidence and "REDACTED" in real.evidence
    fake = [i for i in issues if i.file == "tests/test_x.py"][0]
    assert fake.severity == "low"  # test/example values are downgraded, not hidden


def test_verification_relocates_and_discards():
    from core.schemas import LLMReview
    raw = LLMReview.model_validate(AI).issues
    kept, discarded = verify_audit_issues(raw, {"shop/cart.py": CART})
    by = {i.title: i for i in kept}
    assert by["Mutable default argument"].verification_status == "verified" and by["Mutable default argument"].line == 1
    assert by["Division by zero on empty cart"].line == 8  # wrong line fixed from the quoted evidence
    assert len(discarded) == 1 and "ghost.py" in discarded[0]


def test_scoring_weights_severity_and_confidence():
    focus = ["security", "secrets", "bugs", "performance", "maintainability"]
    assert score_issues([], focus)[0] == 100
    crit = Issue(id="1", file="a", title="t", explanation="e", severity="critical", category="secrets", verification_status="verified")
    score, cats = score_issues([crit], focus)
    assert score <= 49 and {c.key: c.score for c in cats}["secrets"] == 55
    low = Issue(id="2", file="a", title="t", explanation="e", severity="low", category="maintainability", verification_status="plausible")
    s2, _ = score_issues([low], focus)
    assert 95 <= s2 < 100


def test_chunks_number_lines_and_respect_budget():
    big = "\n".join(f"x{i} = {i}" for i in range(3000))
    chunks, cov, lims = build_audit_chunks({"a.py": CART, "big.py": big}, budget=1500, max_chunks=3)
    assert len(chunks) == 3
    assert any("    1 | def add_item(item, cart=[]):" in c.text for c in chunks)
    assert all(len(c.text) / 3.2 <= 1500 * 1.1 for c in chunks)
    assert {c.path: c.status for c in cov}["big.py"] == "partial"


def test_full_repo_audit_end_to_end(tmp_path):
    prov = FakeProvider([AI, SUMMARY])
    db = Database(tmp_path / "a.db")
    aid, r = CodeAuditPipeline(github=_client(), provider=prov, db=db).run("acme/shop", "main")
    titles = {i.title for i in r.issues}
    assert "Possible leaked secret (github token)" in titles and "Mutable default argument" in titles
    assert "subprocess call with shell=True" in titles and "Hallucinated" not in titles
    assert r.commit_sha == "c" * 40 and r.score <= 49 and r.grade == "F"
    assert {c.key for c in r.categories} == {"security", "secrets", "bugs", "performance", "maintainability"}
    assert r.metadata.files_scanned >= 4 and r.metadata.files_analyzed >= 3
    assert any("discarded" in lim for lim in r.limitations)
    sent = " ".join(m["content"] for call in prov.calls for m in call)
    assert FAKE_TOKEN not in sent and "UNTRUSTED_REPOSITORY_DATA" in sent  # redacted + framed as data
    row = db.get_audit(aid)
    assert row["status"] == "completed" and row["score"] == r.score and db.list_audits()[0]["id"] == aid
    assert "## Breakdown" in render_audit_report(r)


def test_folder_and_file_scope(tmp_path):
    _, r = CodeAuditPipeline(github=_client(), provider=FakeProvider([{"summary": "ok", "issues": []}, SUMMARY]),
                             options=AuditOptions(focus=["secrets"])).run("acme/shop", "main", "folder", "tests")
    assert {f.path for f in r.files} == {"tests/test_x.py"} and all(i.category == "secrets" for i in r.issues)
    c = _client()
    c.gh.repo._contents["shop/cart.py"] = CART
    _, r2 = CodeAuditPipeline(github=c, provider=FakeProvider([AI, SUMMARY]),
                              options=AuditOptions(focus=["bugs"])).run("acme/shop", "main", "file", "shop/cart.py")
    assert {i.file for i in r2.issues} == {"shop/cart.py"} and [c.key for c in r2.categories] == ["bugs"]


def test_private_repo_needs_consent_for_hosted_model(tmp_path):
    prov = FakeProvider([AI, SUMMARY])
    db = Database(tmp_path / "a.db")
    with pytest.raises(ConsentRequired):
        CodeAuditPipeline(github=_client(private=True), provider=prov, db=db).run("acme/shop", "main")
    assert prov.calls == [] and db.list_audits()[0]["status"] == "failed"
    local = FakeProvider([AI, SUMMARY], hosted=False)
    assert CodeAuditPipeline(github=_client(private=True), provider=local).run("acme/shop", "main")[1].issues


def test_llm_failure_everywhere_fails_honestly(tmp_path):
    from core.reviewer import ReviewError
    with pytest.raises(ReviewError):
        CodeAuditPipeline(github=_client(), provider=FakeProvider(["junk"] * 3)).run("acme/shop", "main")
