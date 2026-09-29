"""Deterministic checks over PR data. These never execute repository code."""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from typing import Callable

from .context_builder import RepoContext, is_test_path, language_of
from .diff_parser import DiffIndex
from .schemas import Issue, PRData
from .security import find_secret_labels, redact_secrets

_SOURCE_LANGS = {"python", "typescript", "javascript", "go", "rust", "java", "kotlin", "ruby", "csharp", "php", "c", "cpp", "swift", "scala"}

# (regex, languages or None, severity, title, explanation)
_RISKY = [
    (re.compile(r"verify\s*=\s*False"), {"python"}, "medium", "TLS certificate verification disabled",
     "Disabling certificate verification exposes the connection to man-in-the-middle attacks."),
    (re.compile(r"shell\s*=\s*True"), {"python"}, "medium", "subprocess call with shell=True",
     "shell=True passes the command through a shell; unsanitised input allows command injection."),
    (re.compile(r"\b(eval|exec)\s*\("), {"python"}, "medium", "Dynamic code execution (eval/exec)",
     "eval/exec on non-constant input allows arbitrary code execution."),
    (re.compile(r"\bpickle\.loads?\s*\("), {"python"}, "medium", "Unsafe deserialisation with pickle",
     "Unpickling untrusted data can execute arbitrary code."),
    (re.compile(r"\byaml\.load\s*\((?!.*Loader\s*=\s*(?:yaml\.)?(?:Safe|CSafe))"), {"python"}, "medium",
     "yaml.load without SafeLoader", "yaml.load with the default loader can construct arbitrary objects."),
    (re.compile(r"^\s*except\s*:\s*$"), {"python"}, "low", "Bare except clause",
     "A bare except hides unrelated failures (including KeyboardInterrupt) and makes errors hard to diagnose."),
    (re.compile(r"\beval\s*\("), {"javascript", "typescript"}, "medium", "Use of eval()",
     "eval on dynamic input allows arbitrary code execution."),
    (re.compile(r"\.innerHTML\s*=|dangerouslySetInnerHTML"), {"javascript", "typescript"}, "medium",
     "Direct HTML injection sink", "Assigning unsanitised strings to innerHTML enables cross-site scripting."),
    (re.compile(r"rejectUnauthorized\s*:\s*false"), {"javascript", "typescript"}, "medium", "TLS verification disabled",
     "rejectUnauthorized:false disables certificate validation."),
    (re.compile(r"InsecureSkipVerify\s*:\s*true"), {"go"}, "medium", "TLS verification disabled",
     "InsecureSkipVerify:true disables certificate validation."),
]


@dataclass
class StaticReport:
    issues: list[Issue] = field(default_factory=list)
    hints: list[str] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)


def run_static_checks(pr: PRData, ctx: RepoContext, index: DiffIndex, *,
                      fetch_file: Callable[[str], str | None] | None = None,
                      syntax_check: bool = True) -> StaticReport:
    rep = StaticReport()
    n = 0

    def nid() -> str:
        nonlocal n
        n += 1
        return f"S{n}"

    # 1. credentials in added lines + risky patterns
    for path, fd in index.files.items():
        lang = language_of(path)
        for h in fd.hunks:
            for l in h.added:
                labels = find_secret_labels(l.text)
                if labels and not is_test_path(path):
                    red, _ = redact_secrets(l.text)
                    rep.issues.append(Issue(
                        id=nid(), severity="high" if labels[0] == "hardcoded_credential" else "critical", category="security",
                        file=path, line=l.new_no, side="RIGHT",
                        title=f"Possible credential committed ({labels[0].replace('_', ' ')})",
                        explanation="An added line matches a credential/secret pattern. Committed secrets remain in git history "
                                    "and must be rotated even if removed later.",
                        evidence=red.strip()[:200], suggested_fix="Remove the value, load it from the environment or a secret "
                        "manager, and rotate the exposed credential.", verification_status="verified", source="static"))
                    continue
                if is_test_path(path):
                    continue
                for pat, langs, sev, title, expl in _RISKY:
                    if lang in langs and pat.search(l.text):
                        rep.issues.append(Issue(
                            id=nid(), severity=sev, category="security" if sev != "low" else "reliability", file=path,
                            line=l.new_no, side="RIGHT", title=title, explanation=expl + " (pattern-based check; confirm the input is untrusted.)",
                            evidence=l.text.strip()[:200], verification_status="plausible", source="static"))
                        break

    # 2. Python syntax of changed files at the PR head (parsed, never executed)
    if syntax_check and fetch_file:
        checked = 0
        for f in pr.files:
            if f.filename.endswith(".py") and f.status != "removed" and checked < 15:
                src = fetch_file(f.filename)
                if src is None:
                    continue
                checked += 1
                try:
                    ast.parse(src)
                except SyntaxError as e:
                    fd = index.get(f.filename)
                    line = e.lineno if fd and fd.is_valid_location(e.lineno, "RIGHT") else None
                    rep.issues.append(Issue(
                        id=nid(), severity="high", category="bug", file=f.filename, line=line, side="RIGHT",
                        title="Python syntax error in changed file",
                        explanation=f"The file at the PR head does not parse: {e.msg} (line {e.lineno}). It will fail on import.",
                        evidence=(e.text or "").strip()[:200], verification_status="verified", source="static"))
            if f.filename.endswith(".json") and f.status != "removed" and checked < 15:
                src = fetch_file(f.filename)
                if src is not None:
                    try:
                        json.loads(src)
                    except ValueError as e:
                        rep.issues.append(Issue(
                            id=nid(), severity="medium", category="bug", file=f.filename, line=None,
                            title="Invalid JSON in changed file", explanation=f"The file does not parse as JSON: {e}",
                            verification_status="verified", source="static"))

    # 3. tests
    src_files = [f.filename for f in pr.files if language_of(f.filename) in _SOURCE_LANGS and not is_test_path(f.filename)
                 and f.status != "removed" and f.additions >= 5]
    test_files = [f.filename for f in pr.files if is_test_path(f.filename)]
    if src_files and not test_files:
        rep.issues.append(Issue(
            id=nid(), severity="low", category="testing", file=src_files[0], line=None,
            title="Behavioural code changed without any test changes",
            explanation=f"{len(src_files)} source file(s) changed (e.g. {', '.join(src_files[:3])}) but no test files were added "
                        "or modified in this PR.", verification_status="verified", source="static",
            suggested_fix="Add or extend tests covering the changed behaviour."))

    # 4. hints for the model + report
    if ctx.security_paths:
        rep.hints.append("Security-sensitive files changed: " + ", ".join(ctx.security_paths[:8]))
    if ctx.dependency_changes:
        rep.hints.append("Dependency/manifest files changed: " + ", ".join(ctx.dependency_changes[:8]))
    removed = [f.filename for f in pr.files if f.status == "removed"]
    if removed:
        rep.hints.append("Files deleted: " + ", ".join(removed[:8]))
    return rep
