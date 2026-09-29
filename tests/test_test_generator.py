import json

import pytest

from core.context_builder import build_repo_context, detect_test_setup
from core.github_client import GitHubClient
from core.reviewer import Reviewer
from core.schemas import FileChange, PRData, PRRef
from core.test_generator import TestGenerator, normalize_test_path, pick_target
from tests.fixtures.pr_fixture import GOOD_TEST, ORDERS_SRC, TREE, FakeProvider, make_gh


def _setup(files=None, **kw):
    gh, _ = make_gh(files=files, **kw)
    c = GitHubClient("t", gh=gh)
    pr = c.fetch_pr(PRRef(owner="acme", repo="shop", number=7))
    fetch = lambda p: c.get_file_content(pr.ref, p, pr.head_sha)  # noqa: E731
    ctx = build_repo_context(pr, tree=c.get_repo_tree(pr.ref, pr.head_sha), fetch_file=fetch)
    return pr, ctx, fetch


def test_detects_python_pytest_from_real_repo_files():
    pr, ctx, _ = _setup()
    ts = ctx.test_setup
    assert ts.language == "python" and ts.framework == "pytest" and ts.confident and ts.test_dir == "tests"
    assert ts.example_tests == ["tests/test_smoke.py"] or "tests/test_smoke.py" in ts.example_tests


@pytest.mark.parametrize("pkg,expected", [
    ({"devDependencies": {"vitest": "^1"}}, "vitest"), ({"devDependencies": {"jest": "^29"}}, "jest"),
    ({"scripts": {"test": "vitest run"}}, "vitest"), ({"devDependencies": {"mocha": "1"}}, "mocha"), ({}, None)])
def test_detects_js_framework_from_package_json(pkg, expected):
    ts = detect_test_setup("typescript", ["src/a.ts"], {"package.json": json.dumps(pkg)})
    assert ts.framework == expected and (ts.confident == bool(expected))


def test_other_languages_use_their_own_conventions():
    assert detect_test_setup("go", [], {}).framework == "testing"
    assert detect_test_setup("rust", [], {}).framework == "cargo test"
    assert detect_test_setup("java", [], {"pom.xml": "<artifactId>junit-jupiter</artifactId>"}).framework == "junit5"


@pytest.mark.parametrize("lang,fw,src,tdir,expected", [
    ("python", "pytest", "app/orders.py", "tests", "tests/test_orders.py"),
    ("typescript", "vitest", "src/lib/price.ts", None, "src/lib/price.test.ts"),
    ("typescript", "jest", "src/lib/price.ts", "__tests__", "src/lib/__tests__/price.test.ts"),
    ("javascript", "jest", "index.js", None, "index.test.js"),
    ("go", "testing", "pkg/x/calc.go", ".", "pkg/x/calc_test.go"),
    ("rust", "cargo test", "src/lib.rs", "tests", "tests/lib_test.rs"),
    ("java", "junit5", "src/main/java/a/B.java", None, "src/test/java/a/BTest.java")])
def test_test_path_follows_language_conventions(lang, fw, src, tdir, expected):
    assert normalize_test_path(lang, fw, "../../evil.py", src, tdir) == expected


def test_generates_python_test_for_python_project_only():
    pr, ctx, fetch = _setup()
    prov = FakeProvider([GOOD_TEST])
    res = TestGenerator(Reviewer(prov), fetch).generate(pr, ctx, [])
    tf = res.test_file
    assert tf.language == "python" and tf.framework == "pytest" and tf.filename == "tests/test_orders.py"
    assert "def test_parse_qty_rejects_text" in tf.content and tf.execution_status == "not_run"
    assert not tf.needs_verification and tf.artifact_state == "generated"
    prompt = prov.calls[0][1]["content"]
    assert "app/orders.py" in prompt and "def parse_qty" in prompt  # real source is in context
    assert "tests/test_smoke.py" in prompt  # existing conventions shown


def test_python_test_never_generated_for_typescript_project():
    ts_patch = "@@ -1,1 +1,3 @@\n a\n+export function add(a: number, b: number) { return a + b }\n+export const x = 1"
    from tests.fixtures.pr_fixture import make_file
    pr, ctx, fetch = _setup(files=[make_file("src/math.ts", ts_patch, additions=2, deletions=0)],
                            tree=["src/math.ts", "package.json", "src/math.spec.ts"],
                            contents={"package.json": '{"devDependencies": {"vitest": "1"}}', "src/math.ts": "export function add(){}"})
    prov = FakeProvider([{"filename": "tests/test_math.py", "content": "import { add } from './math'\nimport {describe,it,expect} from 'vitest'\n"
                          "describe('add',()=>{it('adds',()=>{expect(add(1,2)).toBe(3)})})", "purpose": "adds"}])
    tf = TestGenerator(Reviewer(prov), fetch).generate(pr, ctx, []).test_file
    assert tf.language == "typescript" and tf.framework == "vitest" and tf.filename == "src/math.test.ts"
    assert "python" not in tf.filename


def test_invented_imports_and_symbols_are_flagged_for_verification():
    pr, ctx, fetch = _setup()
    bad = dict(GOOD_TEST, content="import pytest\nimport totally_made_up_lib\nfrom app.orders import ghost_function\n\n"
                                   "def test_x():\n    assert ghost_function() == 1\n")
    tf = TestGenerator(Reviewer(FakeProvider([bad])), fetch).generate(pr, ctx, []).test_file
    assert tf.needs_verification
    notes = " ".join(tf.verification_notes)
    assert "totally_made_up_lib" in notes and "ghost_function" in notes


def test_syntax_error_gets_one_corrective_retry():
    pr, ctx, fetch = _setup()
    broken = dict(GOOD_TEST, content="def test_x(:\n  pass")
    prov = FakeProvider([broken, GOOD_TEST])
    tf = TestGenerator(Reviewer(prov), fetch).generate(pr, ctx, []).test_file
    assert len(prov.calls) == 2 and "syntax error" in prov.calls[1][-1]["content"] and not tf.needs_verification
    prov2 = FakeProvider([broken, broken])
    tf2 = TestGenerator(Reviewer(prov2), fetch).generate(pr, ctx, []).test_file
    assert tf2.needs_verification and any("syntax error" in n for n in tf2.verification_notes)


def test_missing_context_is_marked_as_requiring_verification():
    pr, ctx, _ = _setup(tree=[])
    ctx.tree_paths = []
    tf = TestGenerator(Reviewer(FakeProvider([GOOD_TEST])), None).generate(pr, ctx, []).test_file
    assert tf.needs_verification and any("unavailable" in n for n in tf.verification_notes)


def test_no_generation_when_nothing_testable():
    pr = PRData(ref=PRRef(owner="o", repo="r", number=1), files=[FileChange(filename="README.md", additions=2, patch="@@ -1 +1,2 @@\n a\n+b")])
    ctx = build_repo_context(pr)
    res = TestGenerator(Reviewer(FakeProvider([])), None).generate(pr, ctx, [])
    assert res.test_file is None and res.reason


def test_pick_target_prefers_largest_source_change_excluding_tests():
    pr, _, _ = _setup()
    assert pick_target(pr, "python") == "app/orders.py"
    assert pick_target(pr, "go") is None
