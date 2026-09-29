"""Repository understanding + token-budgeted, structure-aware diff chunking."""
from __future__ import annotations

import json
import logging
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import Callable

from .diff_parser import Hunk, parse_patch, render_file_diff
from .schemas import FileChange, FileCoverage, PRData

log = logging.getLogger(__name__)

LANG_BY_EXT = {
    ".py": "python", ".ts": "typescript", ".tsx": "typescript", ".js": "javascript", ".jsx": "javascript",
    ".mjs": "javascript", ".cjs": "javascript", ".go": "go", ".rs": "rust", ".java": "java", ".kt": "kotlin",
    ".rb": "ruby", ".cs": "csharp", ".php": "php", ".c": "c", ".h": "c", ".cpp": "cpp", ".cc": "cpp", ".hpp": "cpp",
    ".swift": "swift", ".scala": "scala", ".sh": "shell", ".ps1": "powershell", ".sql": "sql", ".vue": "vue",
}
_LOCK_NAMES = {"package-lock.json", "yarn.lock", "pnpm-lock.yaml", "poetry.lock", "Pipfile.lock", "Cargo.lock",
               "go.sum", "composer.lock", "Gemfile.lock", "uv.lock"}
_GENERATED_HINTS = re.compile(r"(\.min\.(js|css)$|\.map$|\.snap$|(^|/)(dist|build|vendor|node_modules|__generated__)/|"
                              r"\.pb\.go$|_pb2\.py$|\.generated\.)")
_TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|specs)/|(^|/)test_[^/]+$|_test\.(py|go)$|\.(test|spec)\.[jt]sx?$|Tests?\.(java|cs)$")
_SECURITY_PATH = re.compile(r"(?i)(auth|login|password|passwd|session|token|secret|crypt|permission|acl|rbac|oauth|jwt|"
                            r"security|sanitiz|escape|csrf|cors|sql|query|upload|payment)")
_DOC_EXT = {".md", ".rst", ".txt", ".adoc"}


def estimate_tokens(text: str) -> int:
    """Conservative estimate (~3.2 chars/token). Real usage is reported by the provider when available."""
    return math.ceil(len(text) / 3.2) if text else 0


def language_of(path: str) -> str | None:
    return LANG_BY_EXT.get(PurePosixPath(path).suffix.lower())


def is_test_path(path: str) -> bool:
    return bool(_TEST_PATH.search(path))


def is_lockfile(path: str) -> bool:
    return PurePosixPath(path).name in _LOCK_NAMES


def is_generated(path: str) -> bool:
    return bool(_GENERATED_HINTS.search(path))


def file_priority(f: FileChange) -> int:
    """Lower = reviewed first: security-sensitive and behaviour-changing code before tests/docs/config."""
    p = f.filename
    suffix = PurePosixPath(p).suffix.lower()
    score = 50
    lang = language_of(p)
    if lang:
        score = 20
    if _SECURITY_PATH.search(p):
        score -= 15
    if is_test_path(p):
        score = 60
    elif suffix in _DOC_EXT:
        score = 80
    elif suffix in {".json", ".yml", ".yaml", ".toml", ".ini", ".cfg"}:
        score = 45 if not _SECURITY_PATH.search(p) else 30
    if f.status == "removed":
        score += 10
    return score - min(f.additions, 200) // 40  # larger behavioural changes slightly earlier


# ------------------------------------------------------------------------------ repository context
@dataclass
class TestSetup:
    __test__ = False
    language: str | None = None
    framework: str | None = None
    test_dir: str | None = None
    example_tests: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    confident: bool = False


@dataclass
class RepoContext:
    languages: dict[str, int] = field(default_factory=dict)  # language -> added lines (non-test)
    primary_language: str | None = None
    frameworks: list[str] = field(default_factory=list)
    components: list[str] = field(default_factory=list)
    tree_paths: list[str] = field(default_factory=list)
    tree_truncated: bool = False
    manifests: dict[str, str] = field(default_factory=dict)
    test_setup: TestSetup = field(default_factory=TestSetup)
    dependency_changes: list[str] = field(default_factory=list)
    security_paths: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)

    def summary(self) -> str:
        parts = []
        if self.primary_language:
            parts.append(f"primary language: {self.primary_language}")
        if self.languages:
            parts.append("languages by changed lines: " + ", ".join(f"{k}={v}" for k, v in sorted(self.languages.items(), key=lambda kv: -kv[1])[:5]))
        if self.frameworks:
            parts.append("frameworks/libraries: " + ", ".join(self.frameworks[:8]))
        if self.components:
            parts.append("changed components: " + ", ".join(self.components[:8]))
        ts = self.test_setup
        if ts.framework:
            parts.append(f"test framework: {ts.framework}" + (f" (tests in {ts.test_dir})" if ts.test_dir else ""))
        else:
            parts.append("test framework: unknown")
        if self.dependency_changes:
            parts.append("dependency files changed: " + ", ".join(self.dependency_changes[:6]))
        if self.security_paths:
            parts.append("security-sensitive paths touched: " + ", ".join(self.security_paths[:6]))
        return "; ".join(parts)


MANIFEST_NAMES = ["package.json", "pyproject.toml", "requirements.txt", "setup.cfg", "pytest.ini", "tox.ini",
                  "go.mod", "Cargo.toml", "pom.xml", "build.gradle"]
_FRAMEWORK_HINTS = {
    "fastapi": "FastAPI", "flask": "Flask", "django": "Django", "pydantic": "Pydantic", "sqlalchemy": "SQLAlchemy",
    "react": "React", "next": "Next.js", "vue": "Vue", "express": "Express", "nestjs": "NestJS", "svelte": "Svelte",
    "gin-gonic": "Gin", "actix": "Actix", "tokio": "Tokio", "spring": "Spring", "axios": "axios",
}


def detect_test_setup(language: str | None, tree: list[str], manifests: dict[str, str]) -> TestSetup:
    """Infer the repository's actual test framework/layout for ``language``. Never guesses across languages."""
    ts = TestSetup(language=language)
    tests = [p for p in tree if is_test_path(p) and language_of(p) == language]
    ts.example_tests = tests[:5]
    if language == "python":
        blob = "\n".join(v for k, v in manifests.items() if k.endswith(("pyproject.toml", "requirements.txt", "setup.cfg", "pytest.ini", "tox.ini")))
        has_pytest_cfg = any(p.endswith(("pytest.ini", "conftest.py")) for p in tree) or "pytest" in blob.lower()
        if has_pytest_cfg or any(re.search(r"(^|/)test_.*\.py$|_test\.py$", p) for p in tests):
            ts.framework, ts.confident = "pytest", True
        elif any("unittest" in p for p in tests):
            ts.framework = "unittest"
        else:
            ts.framework, ts.notes = "pytest", ["No test framework detected; defaulting to pytest (verify)."]
        ts.test_dir = "tests" if any(p.startswith("tests/") for p in tree) else (str(PurePosixPath(tests[0]).parent) if tests else "tests")
    elif language in ("typescript", "javascript"):
        pkg = manifests.get("package.json", "")
        deps = {}
        try:
            data = json.loads(pkg) if pkg else {}
            deps = {**data.get("dependencies", {}), **data.get("devDependencies", {})}
            script = (data.get("scripts") or {}).get("test", "")
        except ValueError:
            script = ""
        if "vitest" in deps or "vitest" in script or any(re.search(r"vitest\.config", p) for p in tree):
            ts.framework, ts.confident = "vitest", True
        elif "jest" in deps or "jest" in script or any(re.search(r"jest\.config", p) for p in tree):
            ts.framework, ts.confident = "jest", True
        elif "mocha" in deps:
            ts.framework, ts.confident = "mocha", True
        else:
            ts.framework = None
            ts.notes.append("No JS/TS test framework detected in package.json.")
        ts.test_dir = "__tests__" if any("__tests__/" in p for p in tests) else (str(PurePosixPath(tests[0]).parent) if tests else None)
    elif language == "go":
        ts.framework, ts.confident, ts.test_dir = "testing", True, "."
    elif language == "rust":
        ts.framework, ts.confident, ts.test_dir = "cargo test", True, "tests"
    elif language == "java":
        blob = "\n".join(manifests.get(k, "") for k in ("pom.xml", "build.gradle"))
        ts.framework = "junit5" if "junit" in blob.lower() else None
        ts.confident = bool(ts.framework)
    if not ts.framework:
        ts.notes.append("Test framework could not be determined from repository files.")
    return ts


def build_repo_context(pr: PRData, *, tree: tuple[list[str], bool] | None = None,
                       fetch_file: Callable[[str], str | None] | None = None) -> RepoContext:
    ctx = RepoContext()
    lang_lines: Counter[str] = Counter()
    for f in pr.files:
        lang = language_of(f.filename)
        if lang and not is_test_path(f.filename) and f.status != "removed":
            lang_lines[lang] += max(f.additions, 1)
        if is_lockfile(f.filename) or PurePosixPath(f.filename).name in MANIFEST_NAMES:
            ctx.dependency_changes.append(f.filename)
        if _SECURITY_PATH.search(f.filename) and not is_test_path(f.filename):
            ctx.security_paths.append(f.filename)
    ctx.languages = dict(lang_lines)
    ctx.primary_language = lang_lines.most_common(1)[0][0] if lang_lines else (pr.repo_language or "").lower() or None
    comps = Counter(PurePosixPath(f.filename).parts[0] if len(PurePosixPath(f.filename).parts) > 1 else "(root)" for f in pr.files)
    ctx.components = [c for c, _ in comps.most_common(6)]
    if tree:
        ctx.tree_paths, ctx.tree_truncated = tree
        if ctx.tree_truncated:
            ctx.notes.append("Repository tree listing was truncated by GitHub; test-framework detection may be incomplete.")
    if fetch_file and ctx.tree_paths:
        present = [p for p in ctx.tree_paths if PurePosixPath(p).name in MANIFEST_NAMES and p.count("/") <= 1]
        for p in present[:8]:
            txt = fetch_file(p)
            if txt:
                ctx.manifests[p] = txt[:20000]
    elif fetch_file:  # no tree: probe root manifests only
        for name in ("package.json", "pyproject.toml", "requirements.txt", "go.mod", "Cargo.toml"):
            txt = fetch_file(name)
            if txt:
                ctx.manifests[name] = txt[:20000]
    blob = "\n".join(ctx.manifests.values()).lower()
    for key, label in _FRAMEWORK_HINTS.items():
        if re.search(rf"(?<![a-z0-9-]){re.escape(key)}(?![a-z0-9])", blob):
            ctx.frameworks.append(label)
    ctx.test_setup = detect_test_setup(ctx.primary_language, ctx.tree_paths or [f.filename for f in pr.files], ctx.manifests)
    return ctx


# ------------------------------------------------------------------------------ chunking
@dataclass
class Chunk:
    index: int
    files: list[str]
    text: str
    tokens: int
    partial: list[str] = field(default_factory=list)


@dataclass
class ChunkPlan:
    chunks: list[Chunk]
    coverage: list[FileCoverage]
    limitations: list[str]


DEPTH_MAX_CHUNKS = {"quick": 1, "standard": 6, "deep": 20}


def compute_input_budget(context_tokens: int, configured_cap: int, *, output_reserve: int = 4096, overhead: int = 1800) -> int:
    """Tokens available for diff text in one request. Never below a workable floor."""
    total = min(context_tokens, configured_cap) if configured_cap else context_tokens
    return max(total - output_reserve - overhead, 1200)


def build_chunks(pr: PRData, budget_tokens: int, depth: str = "standard") -> ChunkPlan:
    """Split the PR into per-file / per-hunk chunks that each fit ``budget_tokens``.

    Every file ends up in ``coverage`` with an explicit reason if it was skipped or partially covered.
    """
    max_chunks = DEPTH_MAX_CHUNKS.get(depth, 6)
    coverage: list[FileCoverage] = []
    limitations: list[str] = []
    reviewable: list[tuple[FileChange, list[Hunk]]] = []
    for f in pr.files:
        if f.patch_state == "unavailable" or not f.patch:
            reason = f.patch_note or "No patch data available."
            if f.binary:
                coverage.append(FileCoverage(path=f.filename, status="skipped", reason="Binary file"))
            elif f.status == "renamed" and f.changes == 0:
                coverage.append(FileCoverage(path=f.filename, status="skipped", reason="Renamed without content changes"))
            else:
                coverage.append(FileCoverage(path=f.filename, status="unavailable", reason=reason))
            continue
        if is_lockfile(f.filename) or is_generated(f.filename):
            coverage.append(FileCoverage(path=f.filename, status="skipped", reason="Lock/generated/minified file"))
            continue
        hunks = parse_patch(f.patch)
        if not hunks:
            coverage.append(FileCoverage(path=f.filename, status="unavailable", reason="Patch could not be parsed"))
            continue
        reviewable.append((f, hunks))
    reviewable.sort(key=lambda fh: (file_priority(fh[0]), fh[0].filename))

    chunks: list[Chunk] = []
    cur_files: list[str] = []
    cur_parts: list[str] = []
    cur_tokens = 0
    partial_files: dict[str, str] = {}
    dropped: list[str] = []

    def flush() -> None:
        nonlocal cur_files, cur_parts, cur_tokens
        if cur_parts:
            text = "\n\n".join(cur_parts)
            chunks.append(Chunk(index=len(chunks), files=list(dict.fromkeys(cur_files)), text=text, tokens=estimate_tokens(text)))
        cur_files, cur_parts, cur_tokens = [], [], 0

    for f, hunks in reviewable:
        full = render_file_diff(f.filename, hunks, f.status)
        t = estimate_tokens(full)
        pieces: list[tuple[str, int]]
        if t <= budget_tokens:
            pieces = [(full, t)]
        else:  # split by hunk; truncate a single oversized hunk by lines
            pieces = []
            group: list[str] = []
            gt = 0
            head = f"### FILE: {f.filename} ({f.status})"
            for h in hunks:
                ht_text = h.render()
                ht = estimate_tokens(ht_text)
                if ht > budget_tokens - 50:
                    allowed_chars = int((budget_tokens - 80) * 3.2)
                    ht_text = ht_text[:allowed_chars].rsplit("\n", 1)[0] + "\n... [hunk truncated: exceeds context budget]"
                    ht = estimate_tokens(ht_text)
                    partial_files[f.filename] = "A very large hunk was truncated to fit the model context."
                if gt + ht + 30 > budget_tokens and group:
                    pieces.append((head + " (part)\n" + "\n".join(group), gt + 30))
                    group, gt = [], 0
                group.append(ht_text)
                gt += ht
            if group:
                pieces.append((head + (" (part)" if pieces else "") + "\n" + "\n".join(group), gt + 30))
        for text, tok in pieces:
            if cur_tokens + tok > budget_tokens and cur_parts:
                flush()
            if len(chunks) >= max_chunks:
                dropped.append(f.filename)
                break
            cur_files.append(f.filename)
            cur_parts.append(text)
            cur_tokens += tok
    if len(chunks) < max_chunks:
        flush()
    elif cur_parts:
        dropped.extend(cur_files)
        cur_files, cur_parts = [], []

    covered = {fn for c in chunks for fn in c.files}
    for f, _ in reviewable:
        if f.filename in covered and f.filename in dropped:
            coverage.append(FileCoverage(path=f.filename, status="partial",
                                         reason=f"Only part of this file's diff was reviewed ({depth} depth limit)."))
        elif f.filename in covered:
            if f.filename in partial_files:
                coverage.append(FileCoverage(path=f.filename, status="partial", reason=partial_files[f.filename]))
            else:
                coverage.append(FileCoverage(path=f.filename, status="reviewed"))
        else:
            coverage.append(FileCoverage(path=f.filename, status="skipped",
                                         reason=f"Not reviewed: exceeded the {depth} depth limit ({max_chunks} model call(s)). Use a deeper setting."))
    skipped_depth = [c for c in coverage if c.status == "skipped" and c.reason.startswith("Not reviewed")]
    if skipped_depth:
        limitations.append(f"{len(skipped_depth)} file(s) were not analysed because of the {depth} depth limit: "
                           + ", ".join(c.path for c in skipped_depth[:8]) + ("…" if len(skipped_depth) > 8 else ""))
    if partial_files:
        limitations.append("Some very large hunks were truncated to fit the model context: " + ", ".join(partial_files))
    order = {p.filename: i for i, p in enumerate(pr.files)}
    coverage.sort(key=lambda c: order.get(c.path, 1_000_000))
    return ChunkPlan(chunks=chunks, coverage=coverage, limitations=limitations)
