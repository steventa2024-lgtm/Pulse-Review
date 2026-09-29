"""Strongly validated data models shared by the pipeline, database, CLI and dashboard."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

Severity = Literal["critical", "high", "medium", "low"]
Category = Literal[
    "bug", "security", "performance", "testing", "maintainability", "compatibility", "reliability", "secrets"
]
Risk = Literal["low", "medium", "high", "critical"]
VerificationStatus = Literal["verified", "plausible", "unverified"]
ReviewStatus = Literal[
    "pending", "fetching", "analyzing", "generating_tests", "testing",
    "completed", "posted", "failed", "cancelled", "stale",
]
PatchState = Literal["full", "partial", "unavailable"]

SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}
RISK_ORDER = {"low": 0, "medium": 1, "high": 2, "critical": 3}

_CATEGORY_ALIASES = {
    "logic": "bug", "correctness": "bug", "logic error": "bug", "error-handling": "reliability",
    "error handling": "reliability", "exception handling": "reliability", "validation": "bug",
    "input validation": "bug", "vulnerability": "security", "test": "testing", "tests": "testing",
    "test coverage": "testing", "style": "maintainability", "readability": "maintainability",
    "code quality": "maintainability", "perf": "performance", "breaking change": "compatibility",
    "api": "compatibility", "regression": "bug", "concurrency": "reliability", "secret": "secrets",
    "leaked secret": "secrets", "credentials": "secrets", "credential": "secrets", "api key": "secrets", "debugging": "bug",
}
_SEVERITY_ALIASES = {"blocker": "critical", "major": "high", "moderate": "medium", "minor": "low",
                     "info": "low", "warning": "medium", "error": "high", "nit": "low"}


def utcnow_iso() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# ------------------------------------------------------------------ GitHub-side models
class PRRef(BaseModel):
    owner: str
    repo: str
    number: int

    @property
    def full_name(self) -> str:
        return f"{self.owner}/{self.repo}"

    @property
    def url(self) -> str:
        return f"https://github.com/{self.owner}/{self.repo}/pull/{self.number}"

    @property
    def slug(self) -> str:
        return f"{self.owner}/{self.repo}#{self.number}"


class FileChange(BaseModel):
    filename: str
    status: str = "modified"  # added|removed|modified|renamed|copied|changed|unchanged
    additions: int = 0
    deletions: int = 0
    changes: int = 0
    patch: str | None = None
    previous_filename: str | None = None
    binary: bool = False
    patch_state: PatchState = "full"
    patch_note: str | None = None


class PRData(BaseModel):
    ref: PRRef
    title: str = ""
    body: str = ""
    author: str = ""
    state: str = "open"
    draft: bool = False
    base_ref: str = ""
    head_ref: str = ""
    base_sha: str = ""
    head_sha: str = ""
    private: bool = False
    default_branch: str = ""
    repo_language: str | None = None
    html_url: str = ""
    changed_files_reported: int = 0
    files: list[FileChange] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)

    @property
    def partial(self) -> bool:
        return any(f.patch_state != "full" for f in self.files) or len(self.files) < self.changed_files_reported


# ------------------------------------------------------------------ review result
class Issue(BaseModel):
    id: str
    severity: Severity = "medium"
    category: Category = "bug"
    file: str
    line: int | None = None
    side: Literal["RIGHT", "LEFT"] = "RIGHT"
    title: str
    explanation: str
    evidence: str = ""
    suggested_fix: str = ""
    suggested_code: str | None = None
    verification_status: VerificationStatus = "unverified"
    source: Literal["ai", "static"] = "ai"
    included: bool = True  # user selection for publishing


class TestFile(BaseModel):
    __test__ = False  # not a pytest class
    filename: str
    language: str
    framework: str
    content: str
    purpose: str = ""
    execution_status: Literal["not_run", "passed", "failed", "error"] = "not_run"
    execution_output: str | None = None
    needs_verification: bool = False
    verification_notes: list[str] = Field(default_factory=list)
    artifact_state: Literal["generated", "verified", "executed"] = "generated"
    tests_passed: int | None = None
    tests_failed: int | None = None
    duration_seconds: float | None = None


class FileCoverage(BaseModel):
    path: str
    status: Literal["reviewed", "partial", "skipped", "unavailable"]
    reason: str = ""


class ReviewMetadata(BaseModel):
    provider: str = ""
    model: str = ""
    head_sha: str = ""
    base_sha: str = ""
    depth: str = "standard"
    input_tokens: int | None = None
    output_tokens: int | None = None
    chunks: int = 0
    redactions: int = 0
    created_at: str = Field(default_factory=utcnow_iso)


class ReviewResult(BaseModel):
    summary: str = ""
    overall_risk: Risk = "low"
    files_reviewed: list[FileCoverage] = Field(default_factory=list)
    issues: list[Issue] = Field(default_factory=list)
    test_file: TestFile | None = None
    limitations: list[str] = Field(default_factory=list)
    metadata: ReviewMetadata = Field(default_factory=ReviewMetadata)


# ------------------------------------------------------------------ LLM output (lenient input)
def _s(v: Any) -> str:
    return "" if v is None else str(v)


class LLMIssue(BaseModel):
    id: str | None = None
    severity: Severity = "medium"
    category: Category = "bug"
    file: str
    line: int | None = None
    side: Literal["RIGHT", "LEFT"] = "RIGHT"
    title: str
    explanation: str
    evidence: str = ""
    suggested_fix: str = ""
    suggested_code: str | None = None

    @field_validator("severity", mode="before")
    @classmethod
    def _sev(cls, v: Any) -> Any:
        s = _s(v).strip().lower()
        return _SEVERITY_ALIASES.get(s, s)

    @field_validator("category", mode="before")
    @classmethod
    def _cat(cls, v: Any) -> Any:
        s = _s(v).strip().lower()
        return _CATEGORY_ALIASES.get(s, s)

    @field_validator("side", mode="before")
    @classmethod
    def _side(cls, v: Any) -> Any:
        s = _s(v).strip().upper()
        return s if s in ("RIGHT", "LEFT") else "RIGHT"

    @field_validator("line", mode="before")
    @classmethod
    def _line(cls, v: Any) -> Any:
        if v in (None, "", "null"):
            return None
        try:
            n = int(v)
        except (TypeError, ValueError):
            return None
        return n if n > 0 else None

    @field_validator("evidence", "suggested_fix", mode="before")
    @classmethod
    def _txt(cls, v: Any) -> Any:
        return _s(v)


class LLMReview(BaseModel):
    summary: str = ""
    overall_risk: Risk = "low"
    issues: list[LLMIssue] = Field(default_factory=list)

    @field_validator("overall_risk", mode="before")
    @classmethod
    def _risk(cls, v: Any) -> Any:
        s = _s(v).strip().lower()
        return {"none": "low", "minimal": "low", "moderate": "medium", "severe": "critical"}.get(s, s)


class LLMTestFile(BaseModel):
    filename: str
    content: str
    purpose: str = ""
    imports_used: list[str] = Field(default_factory=list)


def issue_sort_key(i: Issue) -> tuple[int, int]:
    ver = {"verified": 0, "plausible": 1, "unverified": 2}[i.verification_status]
    return (SEVERITY_ORDER[i.severity], ver)
