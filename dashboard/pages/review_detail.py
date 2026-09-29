from __future__ import annotations

import dataclasses
import json
from pathlib import Path

from dashboard.components.external import open_external
from nicegui import run, ui

from core.diff_parser import DiffIndex
from core.github_client import GitHubError
from core.publisher import (ConfirmationError, DuplicatePublicationError, PublishError, PublishOptions, StaleReviewError,
                            render_issue_md)
from core.report import render_report
from core.schemas import Issue, PRData, ReviewResult
from core.security import resolve_inside
from core.services import run_sandbox_for_review

from ..components.layout import frame
from ..components.widgets import (copy_button, diff_html, download_button, fmt_time, github_diff_url, pill, risk_badge,
                                  severity_badge, skeleton, status_badge)
from ..context import Ctx

LANG_MAP = {"typescript": "typescript", "javascript": "javascript", "python": "python", "go": "go", "rust": "rust", "java": "java"}


def finding_text(i: Issue, pr_url: str) -> str:
    loc = f"{i.file}" + (f":{i.line}" if i.line else "")
    parts = [f"[{i.severity.upper()}] {i.title}", f"{i.category} • {loc} • {i.verification_status}", "", i.explanation]
    if i.evidence:
        parts += ["", "Evidence:", i.evidence]
    if i.suggested_fix:
        parts += ["", "Suggested fix: " + i.suggested_fix]
    if i.suggested_code:
        parts += ["", i.suggested_code]
    parts += ["", github_diff_url(pr_url, i.file, i.line, i.side)]
    return "\n".join(parts)


def register(ctx: Ctx) -> None:
    @ui.page("/review/{rid}")
    def review_page(rid: str):
        svc = ctx.services
        row = svc.db.get_review(rid)
        with frame(ctx, "history"):
            if not row:
                ui.label("Review not found").classes("zp-h1")
                ui.button("Back to history", on_click=lambda: ui.navigate.to("/history"), color=None).props("flat no-caps").classes("zp-btn-ghost")
                return
            result: ReviewResult | None = svc.db.get_result(rid)
            pr_json = svc.db.get_pr_json(rid)
            pr = PRData.model_validate_json(pr_json) if pr_json else None
            index = DiffIndex(pr.files) if pr else None

            def delete() -> None:
                with ui.dialog() as d, ui.card().classes("zp-card"):
                    ui.label("Delete this review locally?").classes("zp-h2")
                    with ui.row().classes("justify-end w-full"):
                        ui.button("Cancel", on_click=d.close, color=None).props("flat no-caps").classes("zp-btn-ghost")

                        def _do() -> None:
                            svc.db.delete_review(rid)
                            ui.navigate.to("/history")

                        ui.button("Delete", color="negative", on_click=_do)
                d.open()

            # ------------------------------------------------------------------ header
            with ui.element("div").classes("zp-card w-full"):
                with ui.row().classes("items-start justify-between w-full no-wrap"):
                    with ui.column().classes("gap-1"):
                        ui.label(f"{row['repo']} #{row['pr_number']}").classes("zp-muted zp-mono")
                        ui.label(row["pr_title"] or "(untitled pull request)").classes("zp-h1")
                        with ui.row().classes("items-center gap-2"):
                            status_badge(row["status"])
                            if result:
                                risk_badge(result.overall_risk)
                            ui.label(f"{row['provider']} • {row['model']}").classes("zp-muted zp-xs")
                            ui.label(f"commit {row['head_sha'][:8]}" if row["head_sha"] else "").classes("zp-muted zp-xs zp-mono")
                            ui.label(fmt_time(row["updated_at"])).classes("zp-muted zp-xs")
                    with ui.row().classes("gap-1 no-wrap"):
                        ui.button("Open on GitHub", icon="open_in_new", on_click=lambda: open_external(row["pr_url"]), color=None).props("flat no-caps").classes("zp-btn-ghost")
                        ui.button("Re-run", icon="replay", on_click=lambda: ui.navigate.to(f"/review/new?url={row['pr_url']}"), color=None).props("flat no-caps").classes("zp-btn-ghost")
                        ui.button("Delete", icon="delete_outline", on_click=lambda: delete(), color=None).props("flat no-caps").classes("zp-btn-danger")
                if result and result.metadata.input_tokens is not None:
                    ui.label(f"Tokens reported by provider: {result.metadata.input_tokens:,} in / {result.metadata.output_tokens:,} out").classes("zp-muted zp-xs")
                elif result:
                    ui.label("Token usage was not reported by the provider.").classes("zp-muted zp-xs")
                if result and result.metadata.redactions:
                    ui.label(f"{result.metadata.redactions} secret-like value(s) were redacted before code was sent to the hosted model.").classes("zp-muted zp-xs")

            stale_box = ui.column().classes("w-full")
            if row["status"] == "stale":
                stale_banner(stale_box, row["pr_url"])

            if row["status"] in ("failed", "cancelled") and not result:
                with ui.element("div").classes("zp-card w-full"):
                    ui.label("This review did not complete.").classes("zp-err zp-h3")
                    ui.label(row["error"] or "No error was recorded.").classes("zp-small")
                return
            if not result:
                with ui.element("div").classes("zp-card w-full"):
                    ui.label("Review in progress…").classes("zp-h3")
                    skeleton(4)
                ui.timer(2.0, lambda: ui.navigate.reload() if (svc.db.get_review(rid) or {}).get("status") not in ("pending", "fetching", "analyzing", "generating_tests", "testing") else None)
                return

            # ------------------------------------------------------------------ summary
            with ui.element("div").classes("zp-card w-full"):
                ui.label("Review summary").classes("zp-card-title mb-1")
                ui.label(result.summary or "No summary.").classes("zp-small")  # plain text: model output is untrusted
                with ui.row().classes("gap-2 mt-2"):
                    copy_button(render_report(result, pr), "Copy report", "content_copy")
                    download_button(render_report(result, pr), f"zeropulse-review-{row['repo'].replace('/', '_')}-{row['pr_number']}.md", "Download report (.md)", media="text/markdown")
                    download_button(result.model_dump_json(indent=2), f"zeropulse-review-{rid}.json", "Download JSON", media="application/json")

            # ------------------------------------------------------------------ findings
            sel = {i.id: True for i in result.issues}
            ui.label(f"Detected issues ({len(result.issues)})").classes("zp-h2 mt-2")
            if not result.issues:
                with ui.element("div").classes("zp-card w-full"):
                    ui.label("No defensible issues were found in the reviewed changes.").classes("zp-ok")
                    ui.label("The reviewer is instructed not to invent issues. See the limitations below for what was and wasn't inspected.").classes("zp-muted zp-small")
            for n, i in enumerate(result.issues):
                issue_card(i, n == 0, sel, pr, index, row["pr_url"])

            # ------------------------------------------------------------------ test file
            if result.test_file:
                test_panel(ctx, rid, result, row)
            elif any("No test file" in l for l in result.limitations):
                pass

            # ------------------------------------------------------------------ publish
            publish_panel(ctx, rid, row, result, sel, stale_box)

            # ------------------------------------------------------------------ coverage / limitations
            with ui.element("div").classes("zp-card w-full"):
                ui.label("Files inspected").classes("zp-card-title mb-2")
                cols = [{"name": "path", "label": "File", "field": "path", "align": "left"},
                        {"name": "status", "label": "Coverage", "field": "status", "align": "left"},
                        {"name": "reason", "label": "Note", "field": "reason", "align": "left"}]
                ui.table(columns=cols, rows=[c.model_dump() for c in result.files_reviewed], row_key="path", pagination=10).props("flat no-caps").classes("zp-btn-ghost").classes("w-full")
                if result.limitations:
                    ui.label("Limitations").classes("zp-card-title mt-4 mb-1")
                    for l in result.limitations:
                        ui.label("• " + l).classes("zp-warn zp-small")
                else:
                    ui.label("No limitations recorded: every changed file was inspected.").classes("zp-muted zp-small mt-2")

            pubs = svc.db.list_publications(rid)
            if pubs:
                with ui.element("div").classes("zp-card w-full"):
                    ui.label("Publication history").classes("zp-card-title mb-2")
                    for p in pubs:
                        with ui.row().classes("items-center gap-2"):
                            ui.icon("publish", size="18px").classes("zp-muted")
                            ui.link(f"GitHub review {p['github_review_id']}", p["url"], new_tab=True)
                            ui.label(f"{p['mode']} • {p['inline_comments']} inline • commit {p['head_sha'][:8]} • {fmt_time(p['created_at'])}").classes("zp-muted zp-xs")


# ---------------------------------------------------------------------------------------- components
def stale_banner(box, pr_url: str) -> None:
    box.clear()
    with box:
        with ui.element("div").classes("zp-card w-full").style("border-color: var(--zp-amber)"):
            ui.label("⚠ This pull request changed after the review was generated.").classes("zp-warn zp-h3")
            ui.label("Findings may no longer match the code. Publishing is disabled until you run a refreshed review.").classes("zp-small")
            ui.button("Run refreshed review", icon="replay", on_click=lambda: ui.navigate.to(f"/review/new?url={pr_url}")).props("unelevated no-caps color=warning text-color=black")


def issue_card(i: Issue, expanded: bool, sel: dict[str, bool], pr: PRData | None, index: DiffIndex | None, pr_url: str) -> None:
    with ui.expansion(value=expanded).classes("w-full").props("expand-separator") as exp:
        with exp.add_slot("header"):
            with ui.row().classes("items-center gap-2 w-full no-wrap"):
                severity_badge(i.severity)
                pill(i.category, "gray")
                ui.label(i.title).classes("font-medium flex-1")
                ver_tone = {"verified": "ok", "plausible": "medium", "unverified": "gray"}[i.verification_status]
                pill(i.verification_status, ver_tone)
                if i.source == "static":
                    pill("static check", "purple")
        with ui.column().classes("p-4 gap-3 w-full"):
            with ui.row().classes("gap-4 zp-small zp-muted"):
                ui.label(f"File: {i.file}").classes("zp-mono")
                ui.label(f"Line: {i.line}" if i.line else "Line: not anchored (shown in overview)").classes("zp-mono")
                ui.label(f"Side: {i.side}").classes("zp-mono")
            ui.label(i.explanation).classes("zp-small")
            if index and (fd := index.get(i.file)) is not None:
                ui.label("Relevant changed code").classes("zp-card-title")
                ui.html(diff_html(fd, i.line, i.side))
            if i.evidence:
                ui.label("Evidence").classes("zp-card-title")
                ui.code(i.evidence, language="text").classes("w-full")
            if i.suggested_fix:
                ui.label("Suggested fix").classes("zp-card-title")
                ui.label(i.suggested_fix).classes("zp-small")
            if i.suggested_code:
                ui.code(i.suggested_code, language="python" if i.file.endswith(".py") else "text").classes("w-full")
            with ui.row().classes("items-center gap-1"):
                copy_button(finding_text(i, pr_url), "Copy finding")
                if i.suggested_code or i.suggested_fix:
                    copy_button(i.suggested_code or i.suggested_fix, "Copy suggested fix", "code")
                ui.button("Open on GitHub", icon="open_in_new", on_click=lambda: open_external(github_diff_url(pr_url, i.file, i.line, i.side)), color=None).props("flat no-caps").classes("zp-btn-ghost zp-btn-sm")
                ui.space()
                cb = ui.checkbox("Include when publishing", value=True)
                cb.on_value_change(lambda e, iid=i.id: sel.__setitem__(iid, bool(e.value)))


def test_panel(ctx: Ctx, rid: str, result: ReviewResult, row) -> None:
    tf = result.test_file
    assert tf
    with ui.element("div").classes("zp-card w-full"):
        with ui.row().classes("items-center justify-between w-full"):
            ui.label("Proposed test file").classes("zp-h2")
            with ui.row().classes("gap-2"):
                pill(tf.framework, "low")
                state_tone = {"generated": "gray", "verified": "medium", "executed": "ok"}[tf.artifact_state]
                pill("artifact: " + tf.artifact_state, state_tone)
                exec_tone = {"not_run": "gray", "passed": "ok", "failed": "critical", "error": "medium"}[tf.execution_status]
                pill("execution: " + tf.execution_status.replace("_", " "), exec_tone)
        ui.label(tf.filename).classes("zp-mono mt-1")
        ui.label(tf.purpose).classes("zp-small zp-muted")
        if tf.needs_verification:
            with ui.element("div").classes("mt-2"):
                ui.label("⚠ Draft requires verification before use").classes("zp-warn zp-small zp-h3")
                for n in tf.verification_notes:
                    ui.label("• " + n).classes("zp-warn zp-xs")
        ui.code(tf.content, language=LANG_MAP.get(tf.language, "text")).classes("w-full mt-3")
        out_box = ui.column().classes("w-full gap-2")

        def show_results() -> None:
            out_box.clear()
            with out_box:
                if tf.execution_status == "not_run":
                    ui.label(tf.execution_output or "Not executed. Generated tests are proposals until run in a sandbox.").classes("zp-muted zp-small")
                    return
                with ui.row().classes("gap-6 zp-small"):
                    ui.label(f"Status: {tf.execution_status}")
                    ui.label(f"Passed: {tf.tests_passed if tf.tests_passed is not None else '—'}")
                    ui.label(f"Failed: {tf.tests_failed if tf.tests_failed is not None else '—'}")
                    ui.label(f"Duration: {tf.duration_seconds:.2f}s" if tf.duration_seconds is not None else "Duration: —")
                if tf.execution_output:
                    ui.label("Output").classes("zp-card-title")
                    ui.code(tf.execution_output[-6000:], language="text").classes("w-full")

        show_results()
        docker_ok = bool(ctx.status.get("docker_ok"))
        with ui.row().classes("items-center gap-1 mt-2"):
            copy_button(tf.content, "Copy test")
            download_button(tf.content, Path(tf.filename).name, "Download test")
            ui.button("Save locally", icon="save", on_click=lambda: save_local(), color=None).props("flat no-caps").classes("zp-btn-ghost zp-btn-sm")
            run_btn = ui.button("Run in Sandbox", icon="play_circle", on_click=lambda: sandbox_dialog()).props("unelevated no-caps color=primary").classes("zp-btn-sm")
            if not docker_ok:
                run_btn.disable()
                ui.label("Sandbox unavailable — generated test has not been executed.").classes("zp-warn zp-xs")

        def save_local() -> None:
            d = Path(ctx.services.cfg.app.download_dir or Path.home() / "Downloads")
            try:
                d.mkdir(parents=True, exist_ok=True)
                target = resolve_inside(d, Path(tf.filename).name)
                target.write_text(tf.content, encoding="utf-8")
                ui.notify(f"Saved to {target}", type="positive")
            except (OSError, ValueError) as exc:
                ui.notify(f"Could not save: {exc}", type="negative")

        def sandbox_dialog() -> None:
            with ui.dialog() as d, ui.card().classes("zp-card w-[520px] max-w-full"):
                ui.label("Run generated test in an isolated Docker container").classes("zp-h2")
                ui.label("The pull-request code is downloaded from GitHub and executed only inside a container: no network during the test run, "
                         "no host folders, no credentials, CPU/memory limits and a timeout.").classes("zp-small zp-muted")
                install = ui.checkbox("Install dependencies first (network is enabled during installation only)")
                pull = ui.checkbox("Allow Docker to download the base image if it is missing")
                with ui.row().classes("justify-end w-full"):
                    ui.button("Cancel", on_click=d.close, color=None).props("flat no-caps").classes("zp-btn-ghost")

                    async def go() -> None:
                        d.close()
                        out_box.clear()
                        with out_box:
                            with ui.row().classes("items-center gap-2"):
                                ui.spinner()
                                ui.label("Running in sandbox…").classes("zp-small")
                        try:
                            res = await run.io_bound(lambda: run_sandbox_for_review(ctx.services, rid, install_deps=bool(install.value), allow_pull=bool(pull.value)))
                        except GitHubError as exc:
                            ui.notify(exc.message, type="negative")
                            return
                        fresh = ctx.services.db.get_result(rid)
                        if fresh and fresh.test_file:
                            for f in ("execution_status", "execution_output", "tests_passed", "tests_failed", "duration_seconds", "artifact_state"):
                                setattr(tf, f, getattr(fresh.test_file, f))
                        else:
                            tf.execution_output = res.output
                        show_results()

                    ui.button("Run", color="primary", on_click=go)
            d.open()


def publish_panel(ctx: Ctx, rid: str, row, result: ReviewResult, sel: dict[str, bool], stale_box) -> None:
    svc = ctx.services
    blocked = row["status"] == "stale"
    with ui.element("div").classes("zp-card w-full"):
        ui.label("Publish to GitHub").classes("zp-h2")
        ui.label("Nothing is posted automatically. You will preview the exact content, can edit it, and must confirm the repository and PR. "
                 "Reviews are posted as a plain COMMENT — never an approval or change request. Requires pull-request write permission on your token.").classes("zp-muted zp-small")
        with ui.row().classes("items-center gap-4 mt-2"):
            mode = ui.toggle({"overview": "Single overview review", "inline": "Inline comments (verified lines)"}, value="overview").props("no-caps unelevated toggle-color=zpseg toggle-text-color=zpsegtext")
            inc_test = ui.checkbox("Include generated test file", value=False)
            inc_test.set_enabled(result.test_file is not None)
        btn = ui.button("Preview & post…", icon="publish", on_click=lambda: open_publish()).props("unelevated no-caps color=primary")
        if blocked:
            btn.disable()

    async def open_publish() -> None:
        ids = [k for k, v in sel.items() if v]
        try:
            plan = await run.io_bound(lambda: svc.publisher().prepare(rid, PublishOptions(mode=mode.value, issue_ids=ids, include_test=bool(inc_test.value))))
        except StaleReviewError as exc:
            stale_banner(stale_box, row["pr_url"])
            btn.disable()
            ui.notify(str(exc), type="warning", multi_line=True, timeout=8000)
            return
        except (PublishError, GitHubError) as exc:
            ui.notify(getattr(exc, "message", str(exc)), type="negative", multi_line=True)
            return
        slug = plan.ref.slug
        with ui.dialog() as d, ui.card().classes("zp-card w-[920px] max-w-full"):
            ui.label(f"Post review to {slug}").classes("zp-h2")
            ui.label(f"Commit {plan.head_sha[:8]} • mode: {plan.mode} • {len(plan.inline_comments)} inline comment(s) • event: COMMENT").classes("zp-muted zp-xs zp-mono")
            for w in plan.warnings:
                ui.label("⚠ " + w).classes("zp-warn zp-small")
            with ui.tabs().classes("zp-tabs w-full").props("align=left no-caps dense") as tabs:
                t_edit, t_prev = ui.tab("Edit"), ui.tab("Preview")
                t_inline = ui.tab(f"Inline comments ({len(plan.inline_comments)})")
            with ui.tab_panels(tabs, value=t_prev).classes("w-full bg-transparent"):
                with ui.tab_panel(t_edit):
                    editor = ui.textarea(value=plan.body).props("outlined autogrow input-class=zp-mono").classes("w-full")
                with ui.tab_panel(t_prev):
                    preview = ui.markdown(plan.body)  # sanitized by NiceGUI
                with ui.tab_panel(t_inline):
                    if not plan.inline_comments:
                        ui.label("No inline comments; everything is in the overview.").classes("zp-muted zp-small")
                    for c in plan.inline_comments:
                        ui.label(f"{c['path']}:{c['line']} ({c['side']})").classes("zp-mono")
                        ui.code(c["body"], language="markdown").classes("w-full")
            editor.on_value_change(lambda e: preview.set_content(e.value or ""))
            confirm = ui.input(f"Type {slug} to confirm").props("outlined dense").classes("w-full")
            msg = ui.label().classes("zp-small zp-err")
            with ui.row().classes("justify-end w-full"):
                ui.button("Cancel", on_click=d.close, color=None).props("flat no-caps").classes("zp-btn-ghost")
                post = ui.button("Post to GitHub", icon="send", color="primary")
                post.disable()
            confirm.on_value_change(lambda e: post.enable() if (e.value or "").strip() == slug else post.disable())

            async def do_post() -> None:
                post.disable()
                edited = dataclasses.replace(plan, body=editor.value) if editor.value != plan.body else plan
                try:
                    rec = await run.io_bound(lambda: svc.publisher().publish(rid, edited, confirm.value))
                except StaleReviewError as exc:
                    msg.set_text(str(exc))
                    stale_banner(stale_box, row["pr_url"])
                    return
                except DuplicatePublicationError as exc:
                    msg.set_text(str(exc))
                    return
                except (ConfirmationError, PublishError, GitHubError) as exc:
                    msg.set_text(getattr(exc, "message", str(exc)))
                    post.enable()
                    return
                d.close()
                ui.notify(f"Posted: {rec.url}", type="positive", multi_line=True, timeout=8000)
                ui.navigate.reload()

            post.on_click(do_post)
        d.open()
