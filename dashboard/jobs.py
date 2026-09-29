"""Background review jobs. Jobs outlive page navigation; progress is polled by the UI."""
from __future__ import annotations

import logging
import threading
import uuid
from dataclasses import dataclass, field

from core.providers import ProviderError
from core.review_pipeline import ConsentRequired, ProgressEvent, ReviewCancelled, ReviewOptions, STEPS
from core.services import AppServices

log = logging.getLogger(__name__)


@dataclass
class Job:
    id: str
    url: str
    provider: str | None
    model: str | None
    steps: dict[str, tuple[str, str]] = field(default_factory=lambda: {k: ("pending", "") for k, _ in STEPS})
    cancel: threading.Event = field(default_factory=threading.Event)
    done: bool = False
    error: str | None = None
    error_kind: str | None = None  # consent | cancelled | failed
    review_id: str | None = None

    def on_event(self, ev: ProgressEvent) -> None:
        self.steps[ev.step] = (ev.state, ev.detail)


class JobManager:
    def __init__(self, services: AppServices) -> None:
        self.services = services
        self.jobs: dict[str, Job] = {}
        self._lock = threading.Lock()

    def start(self, url: str, options: ReviewOptions, provider: str | None, model: str | None) -> Job:
        job = Job(id=uuid.uuid4().hex[:8], url=url, provider=provider, model=model)
        with self._lock:
            self.jobs[job.id] = job
        threading.Thread(target=self._run, args=(job, options), daemon=True, name=f"review-{job.id}").start()
        return job

    def _run(self, job: Job, options: ReviewOptions) -> None:
        pipe = None
        try:
            pipe = self.services.pipeline(options, provider=job.provider, model=job.model, progress=job.on_event, cancel=job.cancel)
            outcome = pipe.run(job.url)
            job.review_id = outcome.review_id
        except ConsentRequired as exc:
            job.error, job.error_kind = str(exc), "consent"
        except ReviewCancelled:
            job.error, job.error_kind = "Review cancelled.", "cancelled"
        except Exception as exc:  # noqa: BLE001 - surfaced to the user verbatim
            job.error, job.error_kind = getattr(exc, "message", None) or str(exc), "failed"
            if not isinstance(exc, (ProviderError,)) and not hasattr(exc, "message"):
                log.exception("Review job failed")
        finally:
            if pipe is not None and job.review_id is None:
                job.review_id = pipe.review_id
            for k, (state, detail) in list(job.steps.items()):
                if state == "running":
                    job.steps[k] = ("failed" if job.error else "done", detail)
            job.done = True

    def get(self, job_id: str) -> Job | None:
        return self.jobs.get(job_id)

    def active(self) -> list[Job]:
        return [j for j in self.jobs.values() if not j.done]
