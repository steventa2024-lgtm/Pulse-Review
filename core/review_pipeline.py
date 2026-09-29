"""The single review pipeline used by both the CLI and the dashboard."""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass, field
from typing import Callable, Literal

from .context_builder import RepoContext, build_chunks, build_repo_context, compute_input_budget
from .db import Database
from .diff_parser import DiffIndex
from .github_client import GitHubClient, GitHubError, parse_pr_url
from .providers.base import LLMProvider, ProviderError
from .reviewer import (ReviewError, ReviewFocus, Reviewer, derive_risk, finalize_ids, verify_issues)
from .sandbox.runner import UNAVAILABLE_MESSAGE, SandboxRequest, SandboxRunner
from .schemas import (FileCoverage, Issue, LLMIssue, PRData, PRRef, ReviewMetadata, ReviewResult, ReviewStatus,
                      TestFile, issue_sort_key)
from .static_checks import run_static_checks
from .test_generator import TestGenerator

log = logging.getLogger(__name__)

STEPS: list[tuple[str, str]] = [
    ("connect", "Connecting to GitHub"),
    ("fetch", "Fetching changed files"),
    ("analyze", "Analyzing code changes"),
    ("validate", "Validating findings"),
    ("tests", "Generating test"),
    ("sandbox", "Running sandboxed test"),
    ("report", "Preparing report"),
]
_STEP_STATUS: dict[str, ReviewStatus] = {"connect": "fetching", "fetch": "fetching", "analyze": "analyzing",
                                         "validate": "analyzing", "tests": "generating_tests", "sandbox": "testing",
                                         "report": "analyzing"}


class ReviewCancelled(Exception):
    pass


class ConsentRequired(Exception):
    """Private repository content would be sent to a hosted provider without explicit consent."""


@dataclass
class ProgressEvent:
    step: str
    label: str
    state: Literal["running", "done", "skipped", "failed"]
    detail: str = ""


@dataclass
class ReviewOptions:
    depth: Literal["quick", "standard", "deep"] = "standard"
    generate_tests: bool = True
    run_sandbox: bool = False
    sandbox_install_deps: bool = False
    sandbox_allow_pull: bool = False
    security: bool = True
    performance: bool = True
    max_findings: int = 3
    max_context_budget: int = 24000
    private_hosted_consent: bool = False


@dataclass
class ReviewOutcome:
    review_id: str | None
    result: ReviewResult
    pr: PRData


ProgressCb = Callable[[ProgressEvent], None]


class ReviewPipeline:
    def __init__(self, *, github: GitHubClient, provider: LLMProvider, options: ReviewOptions | None = None,
                 db: Database | None = None, sandbox: SandboxRunner | None = None,
                 progress: ProgressCb | None = None, cancel: threading.Event | None = None) -> None:
        self.github = github
        self.provider = provider
        self.opts = options or ReviewOptions()
        self.db = db
        self.sandbox = sandbox
        self._progress = progress or (lambda e: None)
        self.cancel = cancel or threading.Event()
        self.review_id: str | None = None

    # -- helpers ----------------------------------------------------------------------
    def _emit(self, step: str, state: str, detail: str = "") -> None:
        label = dict(STEPS)[step]
        if self.db and self.review_id and state == "running":
            self.db.update_review(self.review_id, status=_STEP_STATUS[step], stage_detail=label)
        self._progress(ProgressEvent(step, label, state, detail))  # type: ignore[arg-type]

    def _check_cancel(self) -> None:
        if self.cancel.is_set():
            raise ReviewCancelled()

    # -- main -------------------------------------------------------------------------
    def run(self, url_or_ref: str | PRRef) -> ReviewOutcome:
        ref = url_or_ref if isinstance(url_or_ref, PRRef) else parse_pr_url(url_or_ref)
        o = self.opts
        if self.db:
            self.review_id = self.db.create_review(repo=ref.full_name, pr_number=ref.number, pr_url=ref.url,
                                                   provider=self.provider.name, model=self.provider.model, depth=o.depth)
        try:
            return self._run(ref)
        except ReviewCancelled:
            self._finish("cancelled", error="Cancelled by user")
            raise
        except ConsentRequired:
            self._finish("failed", error="Private repository content was not sent: hosted-inference consent is required")
            raise
        except (GitHubError, ProviderError, ReviewError) as exc:
            self._finish("failed", error=getattr(exc, "message", None) or str(exc))
            raise
        except Exception as exc:  # noqa: BLE001
            log.exception("Unexpected review failure")
            self._finish("failed", error=f"Unexpected error: {exc}")
            raise

    def _finish(self, status: ReviewStatus, error: str | None = None) -> None:
        if self.db and self.review_id:
            self.db.update_review(self.review_id, status=status, error=error)

    def _run(self, ref: PRRef) -> ReviewOutcome:
        o = self.opts
        # 1. GitHub ---------------------------------------------------------------
        self._emit("connect", "running")
        pr = self._connect_and_fetch(ref)
        if pr.private and self.provider.hosted and not o.private_hosted_consent:
            raise ConsentRequired(
                f"{pr.ref.full_name} is a private repository. Its source code would be sent to the hosted provider "
                f"'{self.provider.name}'. Grant consent explicitly (dashboard checkbox / --allow-private-hosted) or use local Ollama.")
        self._check_cancel()

        # 2. repository understanding + static analysis --------------------------------
        limitations: list[str] = list(pr.limitations)
        head = pr.head_sha
        fetch = lambda path: self._safe_fetch(ref, path, head)  # noqa: E731
        tree = None
        if o.depth != "quick" or o.generate_tests:
            try:
                tree = self.github.get_repo_tree(ref, head)
            except GitHubError as exc:
                limitations.append(f"Repository tree unavailable ({exc.message}); test-framework detection is limited.")
        ctx = build_repo_context(pr, tree=tree, fetch_file=fetch)
        index = DiffIndex(pr.files)
        self._emit("fetch", "done", f"{len(pr.files)} files, +{sum(f.additions for f in pr.files)}/-{sum(f.deletions for f in pr.files)}")
        if self.db and self.review_id:
            self.db.update_review(self.review_id, pr_title=pr.title, author=pr.author, head_sha=pr.head_sha,
                                  base_sha=pr.base_sha, private_repo=int(pr.private))

        self._emit("analyze", "running", "Static checks")
        static = run_static_checks(pr, ctx, index, fetch_file=fetch, syntax_check=o.depth != "quick")
        self._check_cancel()

        # 3. AI review ------------------------------------------------------------------
        focus = ReviewFocus(security=o.security, performance=o.performance, max_findings=o.max_findings)
        reviewer = Reviewer(self.provider, focus)
        ctx_tokens = self.provider.effective_context_length()
        budget = compute_input_budget(ctx_tokens, o.max_context_budget)
        plan = build_chunks(pr, budget, o.depth)
        limitations += plan.limitations + static.limitations
        if o.depth == "deep":  # surrounding source from the PR commit, not just patch snippets
            self._add_source_context(plan, pr, budget, fetch)
        raw: list[LLMIssue] = []
        summaries: list[str] = []
        failed_chunks: list[str] = []
        llm_risk = None
        for chunk in plan.chunks:
            self._check_cancel()
            self._emit("analyze", "running", f"Model call {chunk.index + 1}/{len(plan.chunks)}: {', '.join(chunk.files[:3])}")
            try:
                out = reviewer.review_chunk(pr, chunk, ctx, static.hints)
            except ProviderError as exc:
                if exc.kind in ("auth", "paid_model", "model_not_found", "rate_limit", "unavailable", "timeout") and not raw and chunk.index == 0:
                    raise  # provider-level failure: surface it instead of a hollow "review"
                failed_chunks.append(f"{', '.join(chunk.files[:3])} ({exc.message})")
                self._mark_chunk_failed(plan.coverage, chunk.files, exc.message)
                continue
            except ReviewError as exc:
                failed_chunks.append(f"{', '.join(chunk.files[:3])} (malformed model output)")
                self._mark_chunk_failed(plan.coverage, chunk.files, str(exc))
                continue
            raw += out.issues
            summaries.append(out.summary)
        if plan.chunks and len(failed_chunks) == len(plan.chunks):
            raise ReviewError("The AI analysis failed for every part of the PR: " + "; ".join(failed_chunks))
        if failed_chunks:
            limitations.append("AI analysis failed for: " + "; ".join(failed_chunks) + ". Those files were NOT fully reviewed.")
        if not plan.chunks:
            limitations.append("No reviewable text diffs were available, so the AI review step did not run.")
        self._emit("analyze", "done", f"{len(plan.chunks)} model call(s)")

        # 4. verification -----------------------------------------------------------------
        self._emit("validate", "running")
        v = verify_issues(raw, index, pr)
        if v.discarded:
            limitations.append(f"{len(v.discarded)} AI finding(s) were discarded because they could not be verified against the diff.")
            log.info("Discarded findings: %s", v.discarded)
        limitations += v.notes
        merged = self._merge_static(v.issues, static.issues)
        merged = merged[: max(o.max_findings, 0)] if o.max_findings else merged
        issues = finalize_ids(merged)
        if o.max_findings and len(v.issues) + len(static.issues) > len(issues):
            limitations.append(f"Only the top {o.max_findings} findings are shown (setting: max findings).")
        self._check_cancel()
        summary, risk_hint = ("", None)
        if plan.chunks and summaries:
            if len(plan.chunks) > 1 or issues:
                summary, risk_hint = reviewer.synthesize(pr, issues, summaries, ctx)
            else:
                summary = summaries[0]
        if not summary:
            summary = f"{len(issues)} finding(s) across {len(pr.files)} changed file(s)." if issues else "No defensible issues were found in the reviewed changes."
        risk = derive_risk(issues, risk_hint or llm_risk)
        self._emit("validate", "done", f"{len(issues)} finding(s) kept, {len(v.discarded)} discarded")

        # 5. test generation ----------------------------------------------------------------
        test_file: TestFile | None = None
        if o.generate_tests:
            self._emit("tests", "running")
            gen = TestGenerator(reviewer, fetch).generate(pr, ctx, issues)
            test_file = gen.test_file
            if test_file is None:
                limitations.append(f"No test file was generated: {gen.reason}")
                self._emit("tests", "skipped", gen.reason or "")
            else:
                self._emit("tests", "done", test_file.filename)
        else:
            self._emit("tests", "skipped", "Disabled")
        self._check_cancel()

        # 6. sandbox (opt-in) ------------------------------------------------------------------
        if o.run_sandbox and test_file is not None:
            self._emit("sandbox", "running")
            self._run_sandbox(pr, test_file)
            self._emit("sandbox", "done" if test_file.execution_status in ("passed", "failed") else "failed",
                       test_file.execution_status)
        else:
            self._emit("sandbox", "skipped", "Not requested" if not o.run_sandbox else "No test file")

        # 7. report ----------------------------------------------------------------------------------
        self._emit("report", "running")
        result = ReviewResult(
            summary=summary, overall_risk=risk, files_reviewed=plan.coverage, issues=issues, test_file=test_file,
            limitations=list(dict.fromkeys(limitations)),
            metadata=ReviewMetadata(provider=self.provider.name, model=self.provider.model, head_sha=pr.head_sha,
                                    base_sha=pr.base_sha, depth=o.depth, input_tokens=reviewer.usage.input_tokens,
                                    output_tokens=reviewer.usage.output_tokens, chunks=len(plan.chunks),
                                    redactions=reviewer.redactions))
        if self.db and self.review_id:
            self.db.save_result(self.review_id, result, pr_json=pr.model_dump_json())
            if test_file and test_file.execution_status != "not_run":
                self.db.save_execution(self.review_id, status=test_file.execution_status, passed=test_file.tests_passed,
                                       failed=test_file.tests_failed, duration=test_file.duration_seconds,
                                       output=test_file.execution_output, runner="docker")
            self._finish("completed")
            self.db.mark_pr_reviewed(pr.ref.full_name, pr.ref.number, pr.head_sha)
        self._emit("report", "done")
        return ReviewOutcome(self.review_id, result, pr)

    # -- pieces -----------------------------------------------------------------------
    @staticmethod
    def _add_source_context(plan, pr: PRData, budget: int, fetch) -> None:  # noqa: ANN001
        from .context_builder import estimate_tokens
        removed = {f.filename for f in pr.files if f.status == "removed"}
        for chunk in plan.chunks:
            room = budget - chunk.tokens
            for fn in chunk.files[:3]:
                if fn in removed or room < 400:
                    continue
                src = fetch(fn)
                if src and estimate_tokens(src) <= room * 0.8:
                    chunk.extra[fn] = src
                    room -= estimate_tokens(src)

    def _connect_and_fetch(self, ref: PRRef) -> PRData:
        self._emit("connect", "done")
        self._emit("fetch", "running")
        return self.github.fetch_pr(ref)

    def _safe_fetch(self, ref: PRRef, path: str, sha: str) -> str | None:
        try:
            return self.github.get_file_content(ref, path, sha)
        except GitHubError as exc:
            log.info("Could not fetch %s: %s", path, exc.message)
            return None

    @staticmethod
    def _mark_chunk_failed(cov: list[FileCoverage], files: list[str], why: str) -> None:
        for c in cov:
            if c.path in files:
                c.status, c.reason = "unavailable", f"AI analysis failed: {why[:160]}"

    @staticmethod
    def _merge_static(ai: list[Issue], static: list[Issue]) -> list[Issue]:
        """AI findings first for equal severity; drop static duplicates of the same location."""
        out = list(ai)
        for s in static:
            if any(a.file == s.file and a.line is not None and a.line == s.line for a in ai):
                continue
            out.append(s)
        return sorted(out, key=lambda i: (issue_sort_key(i)[0], 0 if i.source == "ai" else 1, issue_sort_key(i)[1]))

    def _run_sandbox(self, pr: PRData, tf: TestFile) -> None:
        o = self.opts
        if self.sandbox is None:
            tf.execution_status, tf.execution_output = "not_run", UNAVAILABLE_MESSAGE
            return
        ok, reason = self.sandbox.available()
        if not ok:  # never imply an execution happened
            tf.execution_status, tf.execution_output = "not_run", reason or UNAVAILABLE_MESSAGE
            return
        try:
            archive = self.github.download_archive(pr.ref, pr.head_sha)
        except GitHubError as exc:
            tf.execution_status, tf.execution_output = "error", f"Could not download the repository for sandboxing: {exc.message}"
            return
        res = self.sandbox.run(SandboxRequest(repo_zip=archive, test_path=tf.filename, test_content=tf.content,
                                              language=tf.language, framework=tf.framework,
                                              install_dependencies=o.sandbox_install_deps, allow_pull=o.sandbox_allow_pull),
                               self.cancel)
        apply_sandbox_result(tf, res)


def apply_sandbox_result(tf: TestFile, res) -> None:  # noqa: ANN001
    tf.execution_output = res.output
    tf.tests_passed, tf.tests_failed, tf.duration_seconds = res.passed, res.failed, res.duration_seconds
    if res.status in ("passed", "failed"):
        tf.execution_status = res.status
        tf.artifact_state = "executed"
    elif res.status == "unavailable":
        tf.execution_status = "not_run"
    else:
        tf.execution_status = "error"  # timeout / cancelled / infrastructure error: not a test verdict
