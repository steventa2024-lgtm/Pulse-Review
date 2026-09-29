"""Parse test-runner output into pass/fail counts. Never reports success without evidence of passing tests."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass
class ParsedResults:
    passed: int | None = None
    failed: int | None = None
    errors: int = 0
    duration: float | None = None
    collected_nothing: bool = False


_PY_PASSED = re.compile(r"(\d+) passed")
_PY_FAILED = re.compile(r"(\d+) failed")
_PY_ERRORS = re.compile(r"(\d+) errors?")
_PY_TIME = re.compile(r"in ([\d.]+)s")
_JEST = re.compile(r"Tests:\s+(?P<body>.+)")
_VITEST = re.compile(r"^\s*Tests\s+(?P<body>.+)$", re.M)


def _count(pattern: str, text: str) -> int | None:
    m = re.search(rf"(\d+) {pattern}", text)
    return int(m.group(1)) if m else None


def parse_output(language: str, framework: str, output: str) -> ParsedResults:
    r = ParsedResults()
    if language == "python":
        tail = "\n".join(output.strip().splitlines()[-6:])
        r.passed = int(m.group(1)) if (m := _PY_PASSED.search(tail)) else None
        r.failed = int(m.group(1)) if (m := _PY_FAILED.search(tail)) else None
        r.errors = int(m.group(1)) if (m := _PY_ERRORS.search(tail)) else 0
        r.duration = float(m.group(1)) if (m := _PY_TIME.search(tail)) else None
        r.collected_nothing = "no tests ran" in tail or ("collected 0 items" in output)
        if r.passed is None and r.failed is None and not r.errors:
            r.passed = r.failed = None
    elif language in ("javascript", "typescript"):
        m = _JEST.search(output) or _VITEST.search(output)
        if m:
            body = m.group("body")
            r.passed = _count("passed", body) or 0
            r.failed = _count("failed", body) or 0
        t = re.search(r"Time:\s+([\d.]+)\s*s", output) or re.search(r"Duration\s+([\d.]+)\s*s", output)
        r.duration = float(t.group(1)) if t else None
        r.collected_nothing = "No test files found" in output or "no tests found" in output.lower()
    elif language == "go":
        r.passed = len(re.findall(r"^--- PASS", output, re.M)) or None
        r.failed = len(re.findall(r"^--- FAIL", output, re.M)) or 0
    return r


def decide_status(exit_code: int, parsed: ParsedResults) -> str:
    """passed only if exit code 0 AND at least one test verifiably passed with none failing."""
    if exit_code == 0 and (parsed.passed or 0) > 0 and not parsed.failed and not parsed.errors:
        return "passed"
    if parsed.failed or (exit_code == 1 and (parsed.passed is not None or parsed.failed is not None)):
        return "failed"
    return "error"
