from core.context_builder import build_chunks, compute_input_budget, estimate_tokens, file_priority
from core.diff_parser import DiffIndex, parse_patch, parse_unified_diff
from core.schemas import FileChange, PRData, PRRef
from tests.fixtures.pr_fixture import AUTH_PATCH, ORDERS_PATCH, default_files, make_file


def test_hunk_line_numbers_match_real_source_lines():
    (h,) = parse_patch(ORDERS_PATCH)
    adds = {l.new_no: l.text for l in h.added}
    assert adds[14] == "    discount = price * pct / 100"
    assert adds[20] == "    return int(raw)"
    dels = {l.old_no: l.text for l in h.removed}
    assert dels[13] == "def apply_discount(price, pct):"
    ctx = [l for l in h.lines if l.kind == "ctx"]
    assert ctx[0].old_no == 10 and ctx[0].new_no == 10
    assert [l for l in h.lines if l.text.startswith("def checkout")][0].new_no == 22
    assert [l for l in h.lines if l.text.startswith("def checkout")][0].old_no == 16


def test_multiple_hunks_and_no_newline_marker():
    patch = "@@ -1,2 +1,2 @@\n a\n-b\n+B\n\\ No newline at end of file\n@@ -50,2 +50,3 @@ ctx\n x\n+new\n y"
    h1, h2 = parse_patch(patch)
    assert h1.added[0].new_no == 2 and h2.added[0].new_no == 51 and h2.header.strip() == "ctx"


def test_parse_full_git_diff():
    diff = "diff --git a/x.py b/x.py\n--- a/x.py\n+++ b/x.py\n@@ -1 +1,2 @@\n a\n+b\ndiff --git a/n.py b/n.py\nnew file mode 100644\n--- /dev/null\n+++ b/n.py\n@@ -0,0 +1 @@\n+z"
    files = parse_unified_diff(diff)
    assert set(files) == {"x.py", "n.py"} and files["n.py"][0].added[0].new_no == 1


def test_location_validation_for_inline_comments():
    idx = DiffIndex([make_file("app/orders.py", ORDERS_PATCH)])
    fd = idx.get("app/orders.py")
    assert fd.is_valid_location(14, "RIGHT") and fd.is_valid_location(10, "RIGHT")  # added + context visible in diff
    assert not fd.is_valid_location(500, "RIGHT") and not fd.is_valid_location(None)
    assert fd.is_valid_location(13, "LEFT") and not fd.is_valid_location(10, "LEFT")  # LEFT = deleted lines only
    assert fd.is_changed_line(14) and not fd.is_changed_line(10)
    assert fd.contains("discount   =  price * pct / 100") and not fd.contains("nope")
    assert fd.nearest_changed_line("return int(raw)") == 20
    assert not idx.has("missing.py")


def test_evidence_matches_redacted_secret_lines():
    idx = DiffIndex([make_file("app/auth.py", AUTH_PATCH)])
    assert idx.get("app/auth.py").contains('API_TOKEN = "[REDACTED:github_token]"')


def _pr(files):
    return PRData(ref=PRRef(owner="o", repo="r", number=1), files=files, changed_files_reported=len(files))


def _big_file(name, n_lines, added=True):
    body = "\n".join(f"+line_{i} = compute({i}) * 31337 + offset" for i in range(n_lines))
    return FileChange(filename=name, status="modified", additions=n_lines, patch=f"@@ -1,1 +1,{n_lines + 1} @@\n ctx\n{body}")


def test_chunking_respects_budget_and_covers_everything():
    files = [_big_file(f"src/m{i}.py", 60) for i in range(6)]
    plan = build_chunks(_pr(files), 1200, "deep")
    assert len(plan.chunks) > 1
    assert all(c.tokens <= 1200 + 60 for c in plan.chunks)
    assert {c.path for c in plan.coverage if c.status == "reviewed"} == {f.filename for f in files}


def test_large_single_file_split_by_hunks_and_oversized_hunk_marked_partial():
    hunks = "\n".join(f"@@ -{i*100},1 +{i*100},2 @@\n c{i}\n+add{i} = {i}" for i in range(1, 40))
    plan = build_chunks(_pr([FileChange(filename="big.py", additions=39, patch=hunks)]), 300, "deep")
    assert len(plan.chunks) >= 3 and all(c.tokens <= 300 for c in plan.chunks)
    joined = "\n".join(c.text for c in plan.chunks)
    assert all(f"add{i} = {i}" in joined for i in range(1, 40))  # no hunk lost when splitting
    huge = _big_file("huge.py", 2000)
    plan2 = build_chunks(_pr([huge]), 500, "deep")
    cov = plan2.coverage[0]
    assert cov.status == "partial" and "truncated" in cov.reason and plan2.limitations


def test_depth_limit_never_silently_drops_files():
    files = [_big_file(f"src/m{i}.py", 60) for i in range(8)]
    plan = build_chunks(_pr(files), 1000, "quick")
    assert len(plan.chunks) == 1
    skipped = [c for c in plan.coverage if c.status == "skipped"]
    assert skipped and all("depth" in c.reason for c in skipped)
    assert any("not analysed" in l for l in plan.limitations)
    assert len(plan.coverage) == len(files)  # every file accounted for


def test_skips_lock_binary_and_unavailable_with_reasons():
    plan = build_chunks(_pr(default_files_as_changes() + [FileChange(filename="package-lock.json", additions=9000, patch="@@ -1 +1 @@\n+x")]), 4000)
    by = {c.path: c for c in plan.coverage}
    assert by["package-lock.json"].status == "skipped"
    assert by["assets/logo.png"].reason == "Binary file"
    assert by["data/huge.json"].status == "unavailable"
    assert by["app/orders.py"].status == "reviewed"


def default_files_as_changes():
    from core.github_client import GitHubClient
    return [GitHubClient._to_file_change(f) for f in default_files()]


def test_priority_puts_security_code_first_docs_last():
    a = FileChange(filename="app/auth.py", additions=5, patch="x")
    b = FileChange(filename="README.md", additions=5, patch="x")
    c = FileChange(filename="tests/test_x.py", additions=5, patch="x")
    d = FileChange(filename="app/util.py", additions=5, patch="x")
    order = sorted([b, c, d, a], key=file_priority)
    assert order[0] is a and order[-1] is b


def test_budget_uses_real_context_and_reserves_output():
    assert compute_input_budget(8000, 24000) == 8000 - 4096 - 1800
    assert compute_input_budget(200000, 24000) == 24000 - 4096 - 1800
    assert compute_input_budget(1000, 24000) == 1200  # workable floor
    assert estimate_tokens("a" * 320) == 100
