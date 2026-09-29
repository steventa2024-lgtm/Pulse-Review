"""Shared “Run in sandbox” dialog (review page and Test lab)."""
from __future__ import annotations

from typing import Callable

from nicegui import run, ui

from core.github_client import GitHubError
from core.services import run_sandbox_for_review

from .kit import btn


def open_sandbox_dialog(ctx, review_id: str, *, on_start: Callable[[], None] | None = None,
                        on_done: Callable[[object], None] | None = None) -> None:
    with ui.dialog() as d, ui.card().classes("zp-card w-[560px] max-w-full gap-3"):
        ui.label("Run the generated test in the sandbox").classes("zp-h2")
        ui.label("The pull request's code is downloaded from GitHub and run only inside a Docker container: no network while "
                 "the test runs, no access to your files or credentials, CPU/memory limits and a timeout.").classes("zp-sub")
        install = ui.checkbox("Install the project's dependencies first (network on during install only)")
        pull = ui.checkbox("Allow Docker to download the base image if it is missing", value=True)
        ui.label("The first run prepares a small test-runner image (Python + pytest) once — this can take a minute.").classes("zp-hint")
        with ui.row().classes("justify-end w-full gap-2"):
            btn("Cancel", on_click=d.close, kind="ghost")

            async def go() -> None:
                d.close()
                if on_start:
                    on_start()
                try:
                    res = await run.io_bound(lambda: run_sandbox_for_review(ctx.services, review_id, install_deps=bool(install.value),
                                                                            allow_pull=bool(pull.value)))
                except GitHubError as exc:
                    ui.notify(exc.message, type="negative")
                    res = None
                if res is not None:
                    tone = {"passed": "positive", "failed": "warning"}.get(res.status, "negative")
                    ui.notify({"passed": "Sandbox: tests passed", "failed": "Sandbox: tests failed (see output)"}.get(
                        res.status, f"Sandbox: {res.status} — see output"), type=tone)
                if on_done:
                    on_done(res)

            btn("Run", "play_arrow", go, kind="primary")
    d.open()
