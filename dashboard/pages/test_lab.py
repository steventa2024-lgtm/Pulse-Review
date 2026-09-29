from __future__ import annotations

from pathlib import Path

from nicegui import run, ui


from ..components.kit import page_header
from ..components.layout import frame
from ..components.sandbox_dialog import open_sandbox_dialog
from ..components.widgets import copy_button, download_button, fmt_time, pill
from .review_detail import LANG_MAP


def register(ctx) -> None:
    @ui.page("/testlab")
    def test_lab():
        svc = ctx.services
        with frame(ctx, "testlab"):
            page_header("Test lab", "Generated tests across your reviews. They count as executed only after a real sandbox run.")
            with ui.element("div").classes("zp-card w-full"):
                ui.label("Sandbox status").classes("zp-card-title mb-1")
                status = ui.label("Checking Docker…").classes("zp-small")

                async def check() -> None:
                    ok, reason = await run.io_bound(svc.sandbox().available)
                    status.set_text("Docker (Linux containers) is ready. Tests run offline with CPU/memory limits and no host access." if ok else reason)
                    status.classes(replace="zp-small " + ("zp-ok" if ok else "zp-warn"))

                ui.timer(0.1, check, once=True)
                ui.label("Generated tests are proposals. They are marked 'executed' only after a real sandbox run.").classes("zp-muted zp-xs")
            arts = svc.db.list_test_artifacts()
            if not arts:
                with ui.element("div").classes("zp-card w-full"):
                    ui.label("No generated tests yet. Enable 'Generate test file' on a new review.").classes("zp-muted")
            detail = ui.column().classes("w-full gap-3")

            def show(a: dict) -> None:
                detail.clear()
                res = svc.db.get_result(a["review_id"])
                tf = res.test_file if res else None
                with detail:
                    with ui.element("div").classes("zp-card w-full"):
                        with ui.row().classes("items-center justify-between w-full"):
                            ui.label(a["filename"]).classes("zp-h3 zp-mono")
                            with ui.row().classes("gap-2"):
                                pill(a["framework"], "low")
                                if tf:
                                    pill("artifact: " + tf.artifact_state, {"generated": "gray", "verified": "medium", "executed": "ok"}[tf.artifact_state])
                                    pill("execution: " + tf.execution_status.replace("_", " "), {"not_run": "gray", "passed": "ok", "failed": "critical", "error": "medium"}[tf.execution_status])
                        ui.label(a["purpose"]).classes("zp-muted zp-small")
                        ui.code(a["content"], language=LANG_MAP.get(a["language"], "text")).classes("w-full mt-2")
                        if tf and tf.execution_output:
                            ui.label("Last execution output").classes("zp-card-title mt-2")
                            ui.code(tf.execution_output[-5000:], language="text").classes("w-full")
                        with ui.row().classes("gap-1 mt-2"):
                            copy_button(a["content"], "Copy")
                            download_button(a["content"], Path(a["filename"]).name, "Download")
                            ui.button("Open review", icon="open_in_new", on_click=lambda: ui.navigate.to(f"/review/{a['review_id']}"), color=None).props("flat no-caps").classes("zp-btn-ghost zp-btn-sm")
                            rb = ui.button("Run in Sandbox", icon="play_circle", on_click=lambda: run_it(a)).props("unelevated no-caps color=primary").classes("zp-btn-sm")
                            if not ctx.status.get("docker_ok"):
                                rb.disable()
                                ui.label("Sandbox unavailable — generated test has not been executed.").classes("zp-warn zp-xs")

            def run_it(a: dict) -> None:
                open_sandbox_dialog(ctx, a["review_id"], on_done=lambda res: show(a))

            if arts:
                cols = [{"name": "filename", "label": "Test file", "field": "filename", "align": "left"},
                        {"name": "repo", "label": "Repository", "field": "repo", "align": "left"},
                        {"name": "framework", "label": "Framework", "field": "framework", "align": "left"},
                        {"name": "when", "label": "Created", "field": "when", "align": "left"}]
                rows = [{**a, "when": fmt_time(a["created_at"]), "id": a["id"]} for a in arts]
                with ui.element("div").classes("zp-card w-full"):
                    ui.table(columns=cols, rows=rows, row_key="id", pagination=8, selection="single",
                             on_select=lambda e: show(e.selection[0]) if e.selection else None).props("flat no-caps").classes("zp-btn-ghost").classes("w-full")
                show(arts[0])
