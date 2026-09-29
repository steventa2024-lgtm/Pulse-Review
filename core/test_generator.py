"""Generate one repository-appropriate test file for a reviewed PR and check it for obvious defects."""
from __future__ import annotations

import ast
import json
import logging
import re
import sys
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Callable

from .context_builder import RepoContext, is_test_path, language_of
from .providers.base import ProviderError
from .reviewer import ReviewError, Reviewer
from .schemas import Issue, LLMTestFile, PRData, TestFile
from .security import INJECTION_GUARD, safe_relative_path, wrap_untrusted

log = logging.getLogger(__name__)

SUPPORTED = {"python", "typescript", "javascript", "go", "rust", "java"}
NODE_BUILTINS = {"fs", "path", "os", "util", "assert", "events", "stream", "http", "https", "url", "crypto", "child_process",
                 "buffer", "zlib", "querystring", "readline", "timers", "process", "node:test", "node:assert"}
_STDLIB = set(getattr(sys, "stdlib_module_names", ())) | {"pytest", "__future__"}


@dataclass
class TestGenResult:
    __test__ = False
    test_file: TestFile | None
    reason: str | None = None  # why nothing was generated


def pick_target(pr: PRData, language: str | None) -> str | None:
    """The changed source file (of the chosen language) with the most added lines."""
    best, best_n = None, -1
    for f in pr.files:
        if f.status == "removed" or not f.patch or is_test_path(f.filename):
            continue
        if language_of(f.filename) != language:
            continue
        if f.additions > best_n:
            best, best_n = f.filename, f.additions
    return best


def normalize_test_path(language: str, framework: str | None, model_name: str, source: str, test_dir: str | None) -> str:
    """Force conventional placement/naming regardless of what the model proposed."""
    src = PurePosixPath(source)
    stem = src.stem
    proposed = safe_relative_path(model_name or "")
    if language == "python":
        d = test_dir or "tests"
        name = f"test_{stem}.py"
        if proposed and PurePosixPath(proposed).name.startswith("test_") and proposed.endswith(".py"):
            name = PurePosixPath(proposed).name
        return f"{d}/{name}" if d not in (".", "") else name
    if language in ("typescript", "javascript"):
        ext = src.suffix if src.suffix in (".ts", ".tsx", ".js", ".jsx", ".mjs") else ".js"
        ext = ".ts" if ext == ".tsx" else (".js" if ext == ".jsx" else ext)
        if test_dir == "__tests__":
            return f"{src.parent.as_posix()}/__tests__/{stem}.test{ext}".lstrip("./")
        return f"{src.parent.as_posix()}/{stem}.test{ext}".lstrip("./")
    if language == "go":
        return f"{src.parent.as_posix()}/{stem}_test.go".lstrip("./")
    if language == "rust":
        return f"tests/{stem}_test.rs"
    if language == "java":
        p = source.replace("src/main/", "src/test/")
        return str(PurePosixPath(p).with_name(f"{stem}Test.java"))
    return proposed or f"test_{stem}.txt"


# -------------------------------------------------------------------------- validation
def _python_import_notes(code: str, ctx: RepoContext, target: str, target_src: str | None) -> tuple[list[str], str | None]:
    notes: list[str] = []
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return [], f"syntax error line {e.lineno}: {e.msg}"
    tree_paths = ctx.tree_paths
    manifests = "\n".join(ctx.manifests.values()).lower()
    target_mod = PurePosixPath(target).with_suffix("").as_posix()
    target_defs: set[str] = set()
    if target_src:
        try:
            for n in ast.parse(target_src).body:
                if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
                    target_defs.add(n.name)
                elif isinstance(n, ast.Assign):
                    target_defs |= {t.id for t in n.targets if isinstance(t, ast.Name)}
                elif isinstance(n, (ast.Import, ast.ImportFrom)):
                    target_defs |= {(a.asname or a.name).split(".")[0] for a in n.names}
        except SyntaxError:
            pass
    for node in ast.walk(tree):
        mods: list[tuple[str, list[str]]] = []
        if isinstance(node, ast.Import):
            mods = [(a.name, []) for a in node.names]
        elif isinstance(node, ast.ImportFrom) and node.level == 0 and node.module:
            mods = [(node.module, [a.name for a in node.names])]
        for mod, names in mods:
            top = mod.split(".")[0]
            if top in _STDLIB:
                continue
            as_path = mod.replace(".", "/")
            candidates = {as_path + ".py", as_path + "/__init__.py", "src/" + as_path + ".py", "src/" + as_path + "/__init__.py"}
            in_repo = (not tree_paths) or any(p in candidates or p.startswith(as_path + "/") or p.startswith("src/" + as_path + "/") for p in tree_paths)
            in_deps = top.lower().replace("_", "-") in manifests or top.lower() in manifests
            if not in_repo and not in_deps:
                notes.append(f"Import '{mod}' was not found in the repository tree or declared dependencies.")
                continue
            if target_src and as_path in (target_mod, target_mod.removeprefix("src/")):
                for n in names:
                    if n != "*" and n not in target_defs:
                        notes.append(f"'{n}' is imported from {mod} but is not defined at the top level of {target}.")
    return notes, None


def _js_import_notes(code: str, ctx: RepoContext, test_path: str, framework: str | None) -> list[str]:
    notes: list[str] = []
    pkg_deps: set[str] = set()
    try:
        data = json.loads(ctx.manifests.get("package.json", "{}") or "{}")
        pkg_deps = set(data.get("dependencies", {})) | set(data.get("devDependencies", {}))
    except ValueError:
        pass
    tree = set(ctx.tree_paths)
    for m in re.finditer(r"""(?:from\s+|require\(\s*|import\(\s*|import\s+)['"]([^'"]+)['"]""", code):
        spec = m.group(1)
        if spec.startswith("."):
            base = PurePosixPath(test_path).parent.joinpath(spec)
            norm = PurePosixPath(*[p for p in _collapse(base.parts)]).as_posix()
            exts = ["", ".ts", ".tsx", ".js", ".jsx", ".mjs", "/index.ts", "/index.js"]
            if tree and not any((norm + e) in tree for e in exts):
                notes.append(f"Relative import '{spec}' does not resolve to a file in the repository.")
        else:
            pkg = "/".join(spec.split("/")[:2]) if spec.startswith("@") else spec.split("/")[0]
            if pkg in NODE_BUILTINS or pkg.startswith("node:") or pkg in ("vitest", "@jest/globals") and framework in ("vitest", "jest"):
                continue
            if pkg_deps and pkg not in pkg_deps:
                notes.append(f"Package '{pkg}' is not listed in package.json.")
    return notes


def _collapse(parts: tuple[str, ...]) -> list[str]:
    out: list[str] = []
    for p in parts:
        if p == "..":
            if out:
                out.pop()
        elif p != ".":
            out.append(p)
    return out


# -------------------------------------------------------------------------- generator
class TestGenerator:
    __test__ = False

    def __init__(self, reviewer: Reviewer, fetch_file: Callable[[str], str | None] | None = None) -> None:
        self.reviewer = reviewer
        self.fetch_file = fetch_file

    def generate(self, pr: PRData, ctx: RepoContext, issues: list[Issue]) -> TestGenResult:
        language = ctx.test_setup.language or ctx.primary_language
        if not language:
            return TestGenResult(None, "No source language could be determined from the changed files.")
        if language not in SUPPORTED:
            return TestGenResult(None, f"Test generation is not implemented for {language}.")
        target = pick_target(pr, language)
        if not target:
            return TestGenResult(None, f"No changed {language} source file with a usable diff was found.")
        setup = ctx.test_setup
        notes: list[str] = list(setup.notes)
        framework = setup.framework
        if language in ("typescript", "javascript") and not framework:
            framework = "jest"
            notes.append("No JS/TS test framework detected; jest is assumed. Verify before use.")
        needs_verification = not setup.confident
        target_src = self.fetch_file(target) if self.fetch_file else None
        if target_src is None:
            needs_verification = True
            notes.append("Full source of the target file was unavailable; test is based on the diff only.")
        example = None
        if self.fetch_file and setup.example_tests:
            example = self.fetch_file(setup.example_tests[0])
        if not ctx.tree_paths:
            needs_verification = True
            notes.append("Repository tree was unavailable; imports could not be checked against real modules.")

        target_diff = next((f.patch for f in pr.files if f.filename == target), "") or ""
        related = [i for i in issues if i.file == target and i.category != "testing"][:3] or [i for i in issues if i.category != "testing"][:2]
        test_path = normalize_test_path(language, framework, "", target, setup.test_dir)
        prompt = self._prompt(pr, language, framework, target, test_path, target_diff, target_src, example, related, ctx)
        system = ("You write focused, runnable unit tests.\n" + INJECTION_GUARD + "\nRespond with ONE JSON object: "
                  '{"filename": "...", "content": "full test file source", "purpose": "what regression/edge case it covers", '
                  '"imports_used": ["module or package names imported"]}')
        msgs = [{"role": "system", "content": system}, {"role": "user", "content": prompt}]
        try:
            out = self.reviewer._generate_validated(msgs, LLMTestFile, max_tokens=3000)
        except (ReviewError, ProviderError) as exc:
            return TestGenResult(None, f"The model did not return a usable test file: {getattr(exc, 'message', exc)}")

        content = out.content.strip("\n") + "\n"
        content = re.sub(r"^```[a-zA-Z]*\n|```\s*$", "", content).rstrip("\n") + "\n"
        problems: list[str] = []
        if language == "python":
            problems, syntax_err = _python_import_notes(content, ctx, target, target_src)
            if syntax_err:  # one corrective retry
                try:
                    msgs += [{"role": "assistant", "content": out.model_dump_json()},
                             {"role": "user", "content": f"The test file has a {syntax_err}. Return corrected JSON with the full file."}]
                    out = self.reviewer._generate_validated(msgs, LLMTestFile, max_tokens=3000)
                    content = out.content.strip("\n") + "\n"
                    problems, syntax_err = _python_import_notes(content, ctx, target, target_src)
                except (ReviewError, ProviderError):
                    pass
                if syntax_err:
                    problems.append(f"The generated file still has a {syntax_err}.")
        elif language in ("typescript", "javascript"):
            problems = _js_import_notes(content, ctx, test_path, framework)
        elif language == "go" and not re.search(r"^package\s+\w+", content, re.M):
            problems.append("Missing Go package clause.")
        if not content.strip():
            return TestGenResult(None, "The model returned an empty test file.")
        if problems:
            needs_verification = True
            notes += problems
        return TestGenResult(TestFile(
            filename=test_path, language=language, framework=framework or "unknown", content=content,
            purpose=out.purpose.strip() or f"Tests for changes in {target}", needs_verification=needs_verification,
            verification_notes=notes, artifact_state="generated"))

    def _prompt(self, pr: PRData, language: str, framework: str | None, target: str, test_path: str, diff: str,
                src: str | None, example: str | None, related: list[Issue], ctx: RepoContext) -> str:
        parts = [
            f"Write ONE {framework} test file in {language} for the change to `{target}` in {pr.ref.full_name}.",
            f"The file will be saved as `{test_path}`. Use import paths that are valid from that location.",
            "Rules: test only functions/classes that exist in the code shown; do not invent modules, fixtures or dependencies; "
            "include real assertions covering the changed behaviour and at least one regression or edge case; "
            "match the repository's conventions; no network or filesystem side effects.",
            f"Repository context: {ctx.summary()}",
        ]
        if related:
            parts.append("Review findings to cover where possible:\n" + "\n".join(f"- {i.title}: {i.explanation[:240]}" for i in related))
        parts.append(wrap_untrusted("changed_diff", self.reviewer._prep(diff[:9000])))
        if src:
            parts.append(wrap_untrusted(f"full_source_of_{target}", self.reviewer._prep(src[:12000])))
        if example:
            parts.append(wrap_untrusted("existing_test_example", self.reviewer._prep(example[:5000])))
        if ctx.tree_paths:
            near = [p for p in ctx.tree_paths if PurePosixPath(p).parent == PurePosixPath(target).parent or is_test_path(p)][:40]
            parts.append("Real files in the repository (for import paths):\n" + "\n".join(near))
        return "\n\n".join(parts)
