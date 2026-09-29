"""Composition root shared by the CLI and dashboard: builds clients from persisted configuration."""
from __future__ import annotations

import threading

from . import paths
from .config import AppConfig, ConfigManager, load_environment
from .db import Database
from .github_client import GitHubClient
from .providers import LLMProvider, create_provider
from .publisher import Publisher
from .review_pipeline import ProgressCb, ReviewOptions, ReviewPipeline
from .sandbox.docker_runner import DockerRunner
from .sandbox.runner import SandboxRunner
from .watcher import WatchService


class AppServices:
    def __init__(self, config: ConfigManager | None = None, db: Database | None = None,
                 sandbox: SandboxRunner | None = None) -> None:
        load_environment()
        paths.ensure_dirs()
        self.config_mgr = config or ConfigManager()
        self.db = db or Database()
        self.db.recover_interrupted()
        self._sandbox = sandbox

    @property
    def cfg(self) -> AppConfig:
        return self.config_mgr.config

    def github(self) -> GitHubClient:
        from .github_oauth import ensure_fresh_token
        ensure_fresh_token(self.config_mgr)
        return GitHubClient(self.config_mgr.get_github_token(), self.cfg.github.api_base_url)

    def provider(self, provider: str | None = None, model: str | None = None) -> LLMProvider:
        return create_provider(self.cfg, self.config_mgr, provider, model)

    def sandbox(self) -> SandboxRunner:
        if self._sandbox is None:
            self._sandbox = DockerRunner()
        return self._sandbox

    def review_options(self, **overrides) -> ReviewOptions:
        r = self.cfg.review
        base = dict(depth=r.depth, generate_tests=r.generate_tests, run_sandbox=r.run_sandbox_tests,
                    security=r.security_analysis, performance=r.performance_analysis, max_findings=r.max_findings,
                    max_context_budget=r.max_context_budget,
                    private_hosted_consent=self.cfg.openrouter.private_repo_consent)
        base.update({k: v for k, v in overrides.items() if v is not None})
        return ReviewOptions(**base)

    def pipeline(self, options: ReviewOptions, *, provider: str | None = None, model: str | None = None,
                 progress: ProgressCb | None = None, cancel: threading.Event | None = None, persist: bool = True) -> ReviewPipeline:
        return ReviewPipeline(github=self.github(), provider=self.provider(provider, model), options=options,
                              db=self.db if persist else None, sandbox=self.sandbox() if options.run_sandbox else None,
                              progress=progress, cancel=cancel)

    def audit_pipeline(self, options, *, provider: str | None = None, model: str | None = None,
                       progress: ProgressCb | None = None, cancel: threading.Event | None = None):
        from .code_audit import CodeAuditPipeline
        return CodeAuditPipeline(github=self.github(), provider=self.provider(provider, model), options=options,
                                 db=self.db, progress=progress, cancel=cancel)

    def publisher(self) -> Publisher:
        return Publisher(self.github(), self.db)

    def watcher(self) -> WatchService:
        return WatchService(self.github(), self.db)


def run_sandbox_for_review(svc: AppServices, review_id: str, *, install_deps: bool = False, allow_pull: bool = False,
                           cancel: threading.Event | None = None):
    """Execute a stored review's generated test in the sandbox and persist the honest result."""
    from .review_pipeline import apply_sandbox_result
    from .sandbox.runner import UNAVAILABLE_MESSAGE, SandboxRequest, SandboxResult
    from .schemas import PRData

    result = svc.db.get_result(review_id)
    pr_json = svc.db.get_pr_json(review_id)
    if not result or not result.test_file or not pr_json:
        return SandboxResult("error", output="This review has no generated test file.", runner="none")
    tf, pr = result.test_file, PRData.model_validate_json(pr_json)
    runner = svc.sandbox()
    ok, reason = runner.available()
    if not ok:
        return SandboxResult("unavailable", output=reason or UNAVAILABLE_MESSAGE, runner=runner.name)
    archive = svc.github().download_archive(pr.ref, pr.head_sha)
    res = runner.run(SandboxRequest(repo_zip=archive, test_path=tf.filename, test_content=tf.content, language=tf.language,
                                    framework=tf.framework, install_dependencies=install_deps, allow_pull=allow_pull), cancel)
    apply_sandbox_result(tf, res)
    if res.status != "unavailable":
        svc.db.save_result(review_id, result)
        svc.db.save_execution(review_id, status=tf.execution_status, passed=tf.tests_passed, failed=tf.tests_failed,
                              duration=tf.duration_seconds, output=tf.execution_output, runner=runner.name)
    return res
