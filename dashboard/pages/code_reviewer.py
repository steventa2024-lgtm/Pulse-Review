"""Code reviewer: audit a whole repository, a folder or a single file for security, leaked secrets, bugs and more."""
from __future__ import annotations

from nicegui import run, ui

from core.code_audit import AUDIT_STEPS, FOCUS_AREAS, AuditOptions, AuditResult, is_text_candidate, render_audit_report
from core.github_client import GitHubError

from ..components.external import open_external
from ..components.kit import btn, callout, card, empty_state, field, page_header, segmented, select
from ..components.layout import frame
from ..components.widgets import copy_button, download_button, fmt_time, pill, severity_badge
from ..context import Ctx
from .new_review import draw_steps
from .settings import model_options

SKIP = ("node_modules/", ".git/", "__pycache__/", ".venv/", "venv/", "dist/", "build/")


def build_tree(paths: list[str]) -> list[dict]:
    root: dict = {}
    for p in sorted(paths):
        if any(s in p + "/" for s in SKIP):
            continue
        node = root
        parts = p.split("/")
        for i, part in enumerate(parts):
            key = "/".join(parts[: i + 1])
            node = node.setdefault(part, {"__id": key, "__dir": i < len(parts) - 1, "__children": {}})
            if i < len(parts) - 1:
                node["__dir"] = True
            node = node["__children"] if i < len(parts) - 1 else node

    def conv(d: dict) -> list[dict]:
        items = []
        for name, v in d.items():
            if name.startswith("__"):
                continue
            if v.get("__dir"):
                items.append({"id": v["__id"] + "/", "label": name, "icon": "folder", "children": conv(v["__children"])})
            else:
                items.append({"id": v["__id"], "label": name, "icon": "description" if is_text_candidate(v["__id"]) else "insert_drive_file"})
        return sorted(items, key=lambda x: ("children" not in x, x["label"].lower()))

    return conv(root)


SCORE_TONE = lambda s: "positive" if s >= 80 else "warning" if s >= 60 else "negative"  # noqa: E731


def register(ctx: Ctx) -> None:
    @ui.page("/code")
    def code_page(repo: str = ""):
        svc = ctx.services
        cfg = svc.cfg
        st = {"scope_kind": "repo", "scope_path": "", "private": False, "timer": None, "job": None}

        with frame(ctx, "code"):
            page_header("Code reviewer", "Audit a whole repository, a folder or one file for security issues, leaked keys, bugs and more.")
            with ui.row().classes("w-full gap-5 items-start no-wrap max-lg:flex-wrap"):
                with ui.column().classes("gap-5 flex-1 min-w-[380px]"):
                    with card("Repository"):
                        with ui.row().classes("w-full no-wrap items-end gap-2"):
                            with field("Repository", classes="flex-[3] min-w-0"):
                                repo_sel = select({}, classes="w-full", with_input=True).props('placeholder="Loading your repositories…"')
                            with field("Branch", classes="flex-[2] min-w-0"):
                                branch_sel = select({}, classes="w-full", with_input=True).props('placeholder="—"')
                        tree_box = ui.column().classes("w-full gap-2")
                    with card("What to check"):
                        with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-1"):
                            checks = {k: ui.checkbox(v, value=True) for k, v in FOCUS_AREAS.items()}
                        with field("Depth", "Quick: 1 AI call · Standard: up to 6 · Deep: up to 20 (large scopes)"):
                            depth = segmented({"quick": "Quick", "standard": "Standard", "deep": "Deep"}, cfg.review.depth)
                    with card("Model"):
                        prov = segmented({"openrouter": "OpenRouter (free)", "ollama": "Ollama (local)"}, cfg.provider)
                        model_sel = select({}, classes="w-full", with_input=True, new_values=True)
                        model_note = ui.label().classes("zp-hint")
                        consent_box = ui.column().classes("w-full")
                        with consent_box:
                            callout("This repository is private. Its code would be sent to OpenRouter.", "warn")
                            consent = ui.checkbox("I agree to send this repository's code to OpenRouter", value=cfg.openrouter.private_repo_consent)
                        consent_box.set_visibility(False)
                    start_btn = btn("Run code review", "policy", lambda: start(), kind="primary", size="lg").classes("w-full")
                with ui.column().classes("gap-5 w-[380px] max-lg:w-full"):
                    with card("Scope"):
                        scope_lbl = ui.label("Whole repository").classes("zp-h3")
                        scope_hint = ui.label("Select a folder or file in the tree to narrow the scope.").classes("zp-hint")
                        clear_btn = btn("Scan the whole repository", "select_all", lambda: set_scope("repo", ""), kind="ghost", size="sm")
                        clear_btn.set_visibility(False)
                    with card("Progress"):
                        steps_box = ui.column().classes("w-full gap-0")
                        result_box = ui.column().classes("w-full gap-2")
                        cancel_btn = btn("Cancel", "stop", lambda: st["job"] and st["job"].cancel.set(), kind="danger")
                        cancel_btn.set_visibility(False)
                    draw_steps({k: ("pending", "") for k, _ in AUDIT_STEPS}, steps_box, AUDIT_STEPS)

            with card("Recent code reviews"):
                recent_table(ctx)

            # ------------------------------------------------------------------ behaviour
            def set_scope(kind: str, path: str) -> None:
                st["scope_kind"], st["scope_path"] = kind, path
                scope_lbl.set_text({"repo": "Whole repository", "folder": f"Folder  {path}/", "file": f"File  {path}"}[kind])
                scope_hint.set_text("Every text file in the repository is scanned for secrets; the most relevant source files "
                                    "are analysed by the AI." if kind == "repo" else
                                    "Only this " + ("folder" if kind == "folder" else "file") + " will be reviewed.")
                clear_btn.set_visibility(kind != "repo")

            async def load_repos() -> None:
                if not svc.config_mgr.get_github_token():
                    repo_sel.props('placeholder="Sign in to GitHub first (Settings → GitHub)"')
                    return
                try:
                    repos = await run.io_bound(lambda: svc.github().list_repos_detailed())
                except GitHubError as exc:
                    repo_sel.props(f'placeholder="{exc.message[:80]}"')
                    return
                st["repos"] = {r["full_name"]: r for r in repos}
                opts = {r["full_name"]: r["full_name"] + ("  ·  private" if r["private"] else "") for r in repos}
                repo_sel.set_options(opts, value=repo if repo in opts else None)
                repo_sel.props(f'placeholder="{len(opts)} repositories — type to search"')

            async def load_branches() -> None:
                tree_box.clear()
                set_scope("repo", "")
                if not repo_sel.value:
                    return
                st["private"] = bool(st.get("repos", {}).get(repo_sel.value, {}).get("private"))
                update_consent()
                try:
                    names, default = await run.io_bound(lambda: svc.github().list_branches(repo_sel.value))
                except GitHubError as exc:
                    with tree_box:
                        callout(exc.message, "err")
                    return
                branch_sel.set_options(names, value=default)

            async def load_tree() -> None:
                tree_box.clear()
                set_scope("repo", "")
                if not (repo_sel.value and branch_sel.value):
                    return
                with tree_box:
                    with ui.row().classes("items-center gap-2"):
                        ui.spinner(size="16px")
                        ui.label("Loading files…").classes("zp-sub zp-small")
                try:
                    sha, _ = await run.io_bound(lambda: svc.github().resolve_branch(repo_sel.value, branch_sel.value))
                    items, truncated = await run.io_bound(lambda: svc.github().get_tree_sizes(repo_sel.value, sha))
                except GitHubError as exc:
                    tree_box.clear()
                    with tree_box:
                        callout(exc.message, "err")
                    return
                nodes = build_tree([p for p, _ in items])
                tree_box.clear()
                with tree_box:
                    with ui.row().classes("w-full items-center gap-2 no-wrap"):
                        filt = ui.input(placeholder="Filter files…").props("outlined dense clearable hide-bottom-space").classes("flex-1")
                        ui.label(f"{len(items):,} files").classes("zp-xs zp-muted")
                    with ui.element("div").classes("zp-tree w-full"):
                        tree = ui.tree(nodes, label_key="label", node_key="id",
                                       on_select=lambda e: pick(e.value)).props("dense no-transition selected-color=primary")
                    filt.bind_value_to(tree, "filter")
                    if truncated:
                        callout("GitHub truncated the file list for this very large repository; scan a folder for full coverage.", "warn")

            def pick(node_id) -> None:
                if not node_id:
                    set_scope("repo", "")
                elif node_id.endswith("/"):
                    set_scope("folder", node_id.rstrip("/"))
                else:
                    set_scope("file", node_id)

            async def load_models() -> None:
                p = prov.value
                model_note.set_text("Loading models…")
                try:
                    provider = svc.provider(p)
                    if p == "openrouter":
                        models = await run.io_bound(provider.review_models)
                        cur = cfg.openrouter.model
                        opts = model_options(models, cur if cur in {m.id for m in models} else None)
                        cur = cur if cur in opts else (models[0].id if models else cur)
                        model_note.set_text("Verified free models. ★ = best for code review.")
                    else:
                        models = await run.io_bound(provider.list_models)
                        opts = {m.id: m.id for m in models}
                        cur = cfg.ollama.model
                        opts.setdefault(cur, cur)
                        model_note.set_text("Models installed in Ollama on this PC.")
                    model_sel.set_options(opts, value=cur)
                except Exception as exc:  # noqa: BLE001
                    saved = cfg.openrouter.model if p == "openrouter" else cfg.ollama.model
                    model_sel.set_options({saved: saved}, value=saved)
                    model_note.set_text(getattr(exc, "message", str(exc)))
                update_consent()

            def update_consent() -> None:
                consent_box.set_visibility(prov.value == "openrouter" and st["private"])

            def start() -> None:
                if not (repo_sel.value and branch_sel.value):
                    ui.notify("Choose a repository and branch first.", type="warning")
                    return
                focus = [k for k, cb in checks.items() if cb.value]
                if not focus:
                    ui.notify("Select at least one thing to check.", type="warning")
                    return
                if prov.value == "openrouter" and not svc.config_mgr.get_openrouter_key():
                    ui.notify("Add your OpenRouter API key in Settings → AI models.", type="warning")
                    return
                opts = AuditOptions(depth=depth.value, focus=focus, max_context_budget=cfg.review.max_context_budget,
                                    private_hosted_consent=bool(consent.value))
                job = ctx.jobs.start_audit(repo_sel.value, branch_sel.value, st["scope_kind"], st["scope_path"], opts,
                                           prov.value, model_sel.value)
                st["job"] = job
                start_btn.disable()
                cancel_btn.set_visibility(True)
                result_box.clear()
                st["timer"] = ui.timer(0.4, lambda: tick(job))

            def tick(job) -> None:
                draw_steps(job.steps, steps_box, AUDIT_STEPS)
                if not job.done:
                    return
                st["timer"].deactivate()
                start_btn.enable()
                cancel_btn.set_visibility(False)
                result_box.clear()
                with result_box:
                    if job.error:
                        callout(job.error, "warn" if job.error_kind in ("consent", "cancelled") else "err")
                    else:
                        ui.navigate.to(f"/code/{job.review_id}")

            repo_sel.on_value_change(lambda _: load_branches())
            branch_sel.on_value_change(lambda _: load_tree())
            prov.on_value_change(lambda _: load_models())
            ui.timer(0.1, load_repos, once=True)
            ui.timer(0.15, load_models, once=True)

    @ui.page("/code/{aid}")
    def audit_page(aid: str):
        svc = ctx.services
        row = svc.db.get_audit(aid)
        with frame(ctx, "code"):
            if not row:
                empty_state("search_off", "Code review not found")
                return
            if row["status"] != "completed" or not row.get("result_json"):
                with card():
                    ui.label(f"{row['repo']} @ {row['ref']}").classes("zp-mono zp-muted")
                    callout(row.get("error") or f"This code review is {row['status']}.", "err" if row["status"] == "failed" else "info")
                    btn("Back to Code reviewer", "arrow_back", lambda: ui.navigate.to("/code"), kind="secondary").classes("self-start")
                return
            r = AuditResult.model_validate_json(row["result_json"])
            render_audit(r, aid, svc)


def render_audit(r: AuditResult, aid: str, svc) -> None:
    where = {"repo": "Whole repository", "folder": f"Folder {r.scope_path}/", "file": f"File {r.scope_path}"}[r.scope_kind]
    blob = lambda path, line=None: f"https://github.com/{r.repo}/blob/{r.commit_sha}/{path}" + (f"#L{line}" if line else "")  # noqa: E731
    actions = page_header(r.repo, f"{where} · branch {r.ref} @ {r.commit_sha[:8]} · {r.metadata.model}")
    with actions:
        btn("Open on GitHub", "open_in_new", lambda: open_external(f"https://github.com/{r.repo}/tree/{r.commit_sha}/{r.scope_path}"), kind="secondary")
        btn("Run again", "replay", lambda: ui.navigate.to(f"/code?repo={r.repo}"), kind="secondary")

        def delete() -> None:
            svc.db.delete_audit(aid)
            ui.navigate.to("/code")

        btn("Delete", "delete_outline", delete, kind="danger")

    # ---------------------------------------------------------------- score + breakdown
    with ui.row().classes("w-full gap-5 items-stretch no-wrap max-lg:flex-wrap"):
        with ui.element("div").classes("zp-card zp-score-card"):
            ui.label("Overall health").classes("zp-eyebrow")
            with ui.element("div").classes("relative mt-3"):
                ui.circular_progress(value=r.score / 100, min=0, max=1, show_value=False, size="132px",
                                     color=SCORE_TONE(r.score)).props("thickness=0.12 track-color=blue-grey-10 rounded")
                with ui.column().classes("absolute inset-0 items-center justify-center gap-0"):
                    ui.label(str(r.score)).classes("zp-score-num")
                    ui.label(f"grade {r.grade}").classes("zp-xs zp-muted")
            ui.label(f"{len(r.issues)} finding(s) · {r.metadata.files_scanned} files scanned · {r.metadata.files_analyzed} analysed by AI").classes("zp-xs zp-muted mt-3 text-center")
        with ui.element("div").classes("zp-card flex-1"):
            ui.label("Breakdown").classes("zp-h2 mb-2")
            for c in r.categories:
                with ui.row().classes("w-full items-center gap-4 no-wrap py-2"):
                    ui.label(c.label).classes("w-56 zp-small")
                    ui.linear_progress(value=c.score / 100, show_value=False, size="8px", color=SCORE_TONE(c.score)).props("rounded track-color=blue-grey-10").classes("flex-1")
                    ui.label(str(c.score)).classes("w-10 text-right zp-h3")
                    ui.label(f"{c.issues} issue{'s' if c.issues != 1 else ''}").classes("w-20 zp-xs zp-muted")
            ui.label(r.summary).classes("zp-small zp-text-2 mt-3")
            with ui.row().classes("gap-1 mt-1"):
                rep = render_audit_report(r)
                copy_button(rep, "Copy report")
                download_button(rep, f"pulsereview-audit-{r.repo.replace('/', '_')}.md", "Download report (.md)", media="text/markdown")
                download_button(r.model_dump_json(indent=2), f"pulsereview-audit-{aid}.json", "Download JSON", media="application/json")

    # ---------------------------------------------------------------- findings
    cats = ["all"] + [c.key for c in r.categories if c.issues]
    labels = {"all": f"All ({len(r.issues)})", **{c.key: f"{c.label} ({c.issues})" for c in r.categories if c.issues}}
    from core.code_audit import CATEGORY_OF_ISSUE
    with ui.row().classes("w-full items-center justify-between mt-2"):
        ui.label("Findings").classes("zp-h2")
        flt = segmented({k: labels[k] for k in cats}, "all")
    box = ui.column().classes("w-full gap-0")

    def draw() -> None:
        box.clear()
        with box:
            shown = [i for i in r.issues if flt.value == "all" or CATEGORY_OF_ISSUE.get(i.category, "bugs") == flt.value]
            if not shown:
                with ui.element("div").classes("zp-card w-full"):
                    empty_state("verified", "No problems found", "Nothing defensible was found for the selected checks.")
            for n, i in enumerate(shown):
                with ui.expansion(value=n == 0).classes("w-full") as exp:
                    with exp.add_slot("header"):
                        with ui.row().classes("items-center gap-2 w-full no-wrap"):
                            severity_badge(i.severity)
                            pill(i.category, "gray")
                            ui.label(i.title).classes("font-medium flex-1")
                            ui.label(f"{i.file}" + (f":{i.line}" if i.line else "")).classes("zp-mono zp-muted zp-xs")
                            if i.source == "static":
                                pill("scanner", "purple")
                    with ui.column().classes("p-4 gap-3 w-full"):
                        ui.label(i.explanation).classes("zp-small")
                        if i.evidence:
                            ui.code(i.evidence, language="text").classes("w-full")
                        if i.suggested_fix:
                            ui.label("Suggested fix").classes("zp-eyebrow")
                            ui.label(i.suggested_fix).classes("zp-small")
                        if i.suggested_code:
                            ui.code(i.suggested_code, language="python" if i.file.endswith(".py") else "text").classes("w-full")
                        with ui.row().classes("gap-1"):
                            btn("Open line on GitHub", "open_in_new", lambda i=i: open_external(blob(i.file, i.line)), kind="ghost", size="sm")
                            if i.suggested_code or i.suggested_fix:
                                copy_button(i.suggested_code or i.suggested_fix, "Copy fix", "code")
                            ui.label(i.verification_status).classes("zp-xs zp-muted self-center")

    flt.on_value_change(lambda _: draw())
    draw()

    with ui.element("div").classes("zp-card w-full"):
        with ui.expansion(f"Files ({len(r.files)})").classes("w-full").props("dense"):
            cols = [{"name": "path", "label": "File", "field": "path", "align": "left"},
                    {"name": "status", "label": "Coverage", "field": "status", "align": "left"},
                    {"name": "reason", "label": "Note", "field": "reason", "align": "left"}]
            ui.table(columns=cols, rows=[f.model_dump() for f in r.files], row_key="path", pagination=15).props("flat").classes("w-full")
        for lim in r.limitations:
            callout(lim, "warn")


def recent_table(ctx: Ctx) -> None:
    rows = []
    for a in ctx.services.db.list_audits(50):
        scope = a["repo"] + ("" if a["scope_kind"] == "repo" else f" / {a['scope_path']}")
        rows.append({"id": a["id"], "scope": scope, "ref": a["ref"], "score": "—" if a["score"] is None else f"{a['score']} ({a['grade']})",
                     "findings": a["findings_count"], "status": a["status"], "when": fmt_time(a["updated_at"])})
    if not rows:
        empty_state("policy", "No code reviews yet", "Pick a repository above and run your first code review.")
        return
    cols = [{"name": "scope", "label": "Repository / scope", "field": "scope", "align": "left"},
            {"name": "ref", "label": "Branch", "field": "ref", "align": "left"},
            {"name": "score", "label": "Score", "field": "score", "align": "left"},
            {"name": "findings", "label": "Findings", "field": "findings", "align": "center"},
            {"name": "status", "label": "Status", "field": "status", "align": "left"},
            {"name": "when", "label": "Updated", "field": "when", "align": "left"}]
    t = ui.table(columns=cols, rows=rows, row_key="id", pagination=8).props("flat").classes("w-full zp-clickable")
    t.on("rowClick", lambda e: ui.navigate.to(f"/code/{e.args[1]['id']}"))
