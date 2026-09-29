from __future__ import annotations

from nicegui import run, ui

from core.github_client import GitHubError, InvalidPRUrl, parse_pr_url
from core.providers import ProviderError
from core.review_pipeline import STEPS
from core.schemas import PRRef

from ..components.kit import btn, callout, card, field, page_header, segmented, select, text_input  # noqa: F401
from ..components.layout import frame
from ..components.widgets import pill
from ..context import Ctx
from .settings import model_options


def register(ctx: Ctx) -> None:
    @ui.page("/review/new")
    def new_review(url: str = ""):
        svc = ctx.services
        cfg = svc.cfg
        state = {"preview_private": False, "job": None, "timer": None, "prs": {}}

        with frame(ctx, "new"):
            page_header("New review", "Pick a repository and pull request, choose a model, and start. Nothing is posted to GitHub.")
            with ui.row().classes("w-full gap-5 items-start no-wrap max-lg:flex-wrap"):
                # ------------------------------------------------------------ left: form
                with ui.column().classes("gap-5 flex-1 min-w-[360px]"):
                    with card("Pull request"):
                        with ui.row().classes("w-full no-wrap items-end gap-2"):
                            with field("Repository", classes="flex-1 min-w-0"):
                                repo_sel = select({}, classes="w-full", with_input=True).props('placeholder="Loading your repositories…"')
                            btn(icon="refresh", on_click=lambda: load_repos(), kind="secondary", tooltip="Reload repositories")
                        with field("Pull request"):
                            pr_sel = select({}, classes="w-full", with_input=True).props('placeholder="Choose a repository first"')
                        pr_sel.disable()
                        with ui.expansion("Or paste a pull-request link", value=bool(url)).classes("w-full").props("dense") as link_exp:
                            with ui.row().classes("w-full no-wrap items-center gap-2 pt-2"):
                                url_in = text_input("https://github.com/owner/repo/pull/123", value=url, classes="flex-1")
                                btn("Look up", "search", lambda: check_pr(), kind="secondary")
                        preview = ui.column().classes("w-full gap-2")

                    with card("Model"):
                        prov = segmented({"openrouter": "OpenRouter (free)", "ollama": "Ollama (local)"}, cfg.provider)
                        model_sel = select({}, classes="w-full", with_input=True, new_values=True)
                        model_note = ui.label().classes("zp-hint")

                    with card("Options"):
                        with field("Depth", "Quick: 1 model call · Standard: up to 6 · Deep: up to 20 with full-file context"):
                            depth = segmented({"quick": "Quick", "standard": "Standard", "deep": "Deep"}, cfg.review.depth)
                        with ui.grid(columns=2).classes("w-full gap-x-6 gap-y-1"):
                            gen = ui.checkbox("Generate a test file", value=cfg.review.generate_tests)
                            sec = ui.checkbox("Security analysis", value=cfg.review.security_analysis)
                            sandbox = ui.checkbox("Run the test in the sandbox", value=cfg.review.run_sandbox_tests)
                            perf = ui.checkbox("Performance analysis", value=cfg.review.performance_analysis)
                        sb_box = ui.column().classes("w-full gap-1 pl-2")
                        with sb_box:
                            sb_install = ui.checkbox("Install the project's dependencies first (network on during install only)")
                            sb_pull = ui.checkbox("Allow Docker to download the base image if missing")
                        with ui.row().classes("items-center gap-2 no-wrap") as sb_note_row:
                            sb_note = ui.label().classes("zp-hint zp-warn")
                            btn("Set up sandbox", "build", lambda: ui.navigate.to("/settings?tab=app"), kind="ghost", size="sm")
                        consent_box = ui.column().classes("w-full")
                        with consent_box:
                            callout("This is a private repository. Its code would be sent to OpenRouter.", "warn")
                            consent = ui.checkbox("I agree to send this repository's code to OpenRouter", value=cfg.openrouter.private_repo_consent)
                        consent_box.set_visibility(False)

                    start_btn = btn("Start review", "play_arrow", lambda: start(), kind="primary", size="lg").classes("w-full")

                # ------------------------------------------------------------ right: progress
                with ui.column().classes("gap-5 w-[380px] max-lg:w-full"):
                    with card("Progress"):
                        steps_box = ui.column().classes("w-full gap-0")
                        result_box = ui.column().classes("w-full gap-2")
                        cancel_btn = btn("Cancel review", "stop", lambda: cancel(), kind="danger")
                        cancel_btn.set_visibility(False)
                    draw_steps({k: ("pending", "") for k, _ in STEPS}, steps_box)

            # ---------------------------------------------------------------- behaviour
            def sync_sandbox() -> None:
                ok = bool(ctx.status.get("docker_ok"))
                sandbox.set_enabled(ok and bool(gen.value))
                if not ok and sandbox.value:
                    sandbox.value = False
                sb_note.set_text("" if ok else str(ctx.status.get("docker_reason") or ""))
                sb_note_row.set_visibility(not ok)
                sb_box.set_visibility(bool(sandbox.value))

            sandbox.on_value_change(lambda _: sync_sandbox())
            gen.on_value_change(lambda _: sync_sandbox())
            ui.timer(2.0, sync_sandbox)
            sync_sandbox()

            guard = {"loading": False}

            async def load_models(force: bool = False) -> None:
                guard["loading"] = True
                p = prov.value
                model_note.set_text("Loading models…")
                model_note.classes(replace="zp-hint")
                try:
                    provider = svc.provider(p)
                    if p == "openrouter":
                        models = await run.io_bound(lambda: provider.review_models(force))
                        current = cfg.openrouter.model
                        opts = model_options(models, current if current in {m.id for m in models} else None)
                        if current not in opts and models:
                            model_note.set_text(f"“{current}” is no longer free. Choose a model — ★ = best for code review.")
                            model_note.classes(replace="zp-hint zp-warn")
                            current = models[0].id
                        else:
                            model_note.set_text("Verified free models. Paid models are never used.")
                    else:
                        models = await run.io_bound(provider.list_models)
                        opts = {m.id: m.id for m in models}
                        current = cfg.ollama.model
                        if current not in opts:
                            opts[current] = f"{current}  ·  not installed"
                        model_note.set_text("Models installed in Ollama on this PC.")
                    model_sel.set_options(opts, value=current)
                except Exception as exc:  # noqa: BLE001 - offline catalog: keep the saved choice (still verified before use)
                    saved = cfg.openrouter.model if p == "openrouter" else cfg.ollama.model
                    model_sel.set_options({saved: saved}, value=saved)
                    model_note.set_text(getattr(exc, "message", str(exc)))
                    model_note.classes(replace="zp-hint zp-warn")
                guard["loading"] = False
                update_consent()

            def update_consent() -> None:
                consent_box.set_visibility(prov.value == "openrouter" and state["preview_private"])

            prov.on_value_change(lambda _: load_models())

            async def check_pr() -> None:
                preview.clear()
                try:
                    ref = parse_pr_url(url_in.value)
                except InvalidPRUrl as exc:
                    with preview:
                        callout(str(exc), "err")
                    return
                with preview:
                    with ui.row().classes("items-center gap-2"):
                        ui.spinner(size="16px")
                        ui.label("Looking up the pull request…").classes("zp-sub zp-small")
                try:
                    data = await run.io_bound(lambda: svc.github().fetch_pr(ref))
                except GitHubError as exc:
                    preview.clear()
                    with preview:
                        callout(exc.message, "err")
                    return
                state["preview_private"] = data.private
                preview.clear()
                with preview:
                    with ui.element("div").classes("zp-callout"):
                        with ui.row().classes("items-center gap-2"):
                            ui.label(f"{data.ref.full_name} #{data.ref.number}").classes("zp-mono zp-muted")
                            pill("private", "medium") if data.private else pill("public", "gray")
                            pill(data.state, "ok" if data.state == "open" else "gray")
                        ui.label(data.title).classes("zp-h3 mt-1")  # plain text (untrusted)
                        ui.label(f"{data.author} · {data.base_ref} ← {data.head_ref} · {len(data.files)} files · "
                                 f"+{sum(f.additions for f in data.files)} −{sum(f.deletions for f in data.files)}").classes("zp-sub zp-small")
                    for lim in data.limitations:
                        callout(lim, "warn")
                update_consent()

            def cancel() -> None:
                job = state["job"]
                if job and not job.done:
                    job.cancel.set()
                    ui.notify("Cancelling after the current step…")

            async def start() -> None:
                if not (url_in.value or "").strip():
                    ui.notify("Choose a repository and a pull request first.", type="warning")
                    return
                try:
                    ref: PRRef = parse_pr_url(url_in.value)
                except InvalidPRUrl as exc:
                    ui.notify(str(exc), type="negative")
                    return
                if not svc.config_mgr.get_github_token():
                    ui.notify("Sign in to GitHub first (Settings → GitHub).", type="warning")
                    return
                p = prov.value
                if p == "openrouter" and not svc.config_mgr.get_openrouter_key():
                    ui.notify("Add your OpenRouter API key in Settings → AI models.", type="warning")
                    return
                model = model_sel.value
                if not model:
                    ui.notify("Choose a model.", type="warning")
                    return
                opts = svc.review_options(depth=depth.value, generate_tests=bool(gen.value), run_sandbox=bool(sandbox.value and gen.value),
                                          security=bool(sec.value), performance=bool(perf.value),
                                          private_hosted_consent=bool(consent.value))
                opts.sandbox_install_deps, opts.sandbox_allow_pull = bool(sb_install.value), bool(sb_pull.value)
                if p == "openrouter":
                    svc.config_mgr.update(provider=p, openrouter={"model": model})
                else:
                    svc.config_mgr.update(provider=p, ollama={"model": model})
                ctx.refresh_static()
                result_box.clear()
                start_btn.disable()
                cancel_btn.set_visibility(True)
                job = ctx.jobs.start(ref.url, opts, p, model)
                state["job"] = job
                state["timer"] = ui.timer(0.4, lambda: tick(job))

            def tick(job) -> None:
                draw_steps(job.steps, steps_box)
                if not job.done:
                    return
                state["timer"].deactivate()
                start_btn.enable()
                cancel_btn.set_visibility(False)
                result_box.clear()
                with result_box:
                    if job.error:
                        callout(job.error, "warn" if job.error_kind in ("consent", "cancelled") else "err")
                        if job.review_id:
                            btn("View record", on_click=lambda: ui.navigate.to(f"/review/{job.review_id}"), kind="ghost")
                    else:
                        ui.navigate.to(f"/review/{job.review_id}")

            async def load_repos() -> None:
                if not svc.config_mgr.get_github_token():
                    repo_sel.props('placeholder="Sign in to GitHub first (Settings → GitHub)"')
                    link_exp.set_value(True)
                    return
                repo_sel.props('placeholder="Loading your repositories…"')
                try:
                    repos = await run.io_bound(lambda: svc.github().list_repos_detailed())
                except GitHubError as exc:
                    repo_sel.props(f'placeholder="{exc.message[:80]}"')
                    link_exp.set_value(True)
                    return
                opts = {r["full_name"]: r["full_name"] + ("  ·  private" if r["private"] else "") for r in repos}
                current = repo_sel.value if repo_sel.value in opts else None
                if url and not current:
                    try:
                        ref0 = parse_pr_url(url)
                        current = ref0.full_name if ref0.full_name in opts else None
                    except InvalidPRUrl:
                        pass
                repo_sel.set_options(opts, value=current)
                repo_sel.props(f'placeholder="{len(opts)} repositories — type to search"' if opts else 'placeholder="No repositories found for this account"')

            async def load_prs() -> None:
                pr_sel.set_options({}, value=None)
                if not repo_sel.value:
                    pr_sel.disable()
                    return
                pr_sel.props('placeholder="Loading open pull requests…"')
                try:
                    prs = await run.io_bound(lambda: svc.github().list_pull_requests(repo_sel.value))
                except GitHubError as exc:
                    pr_sel.props(f'placeholder="{exc.message[:80]}"')
                    return
                state["prs"] = {p.url: p for p in prs}
                opts = {p.url: f"#{p.number}  {p.title}" + ("  · draft" if p.draft else "") + f"  ·  {p.author}" for p in prs}
                pre = url if url in opts else None
                pr_sel.set_options(opts, value=pre)
                pr_sel.props(f'placeholder="{len(opts)} open pull requests"' if opts else 'placeholder="No open pull requests in this repository"')
                pr_sel.enable() if opts else pr_sel.disable()

            async def on_pr(e) -> None:
                if e.value:
                    url_in.set_value(e.value)
                    await check_pr()

            repo_sel.on_value_change(lambda _: load_prs())
            pr_sel.on_value_change(on_pr)

            ui.timer(0.1, lambda: load_models(), once=True)
            ui.timer(0.15, lambda: load_repos(), once=True)
            if url:
                ui.timer(0.3, lambda: check_pr(), once=True)


def draw_steps(steps: dict[str, tuple[str, str]], box) -> None:
    box.clear()
    with box:
        for key, label in STEPS:
            state, detail = steps.get(key, ("pending", ""))
            with ui.element("div").classes("zp-step"):
                if state == "running":
                    ui.spinner(size="18px", color="primary")
                else:
                    icon, color = {"done": ("check_circle", "zp-ok"), "failed": ("error", "zp-err"),
                                   "skipped": ("remove_circle_outline", "zp-muted"), "pending": ("radio_button_unchecked", "zp-muted")}[state]
                    ui.icon(icon, size="18px").classes(color)
                with ui.column().classes("gap-0"):
                    ui.label(label).classes("zp-small" + (" zp-muted" if state in ("pending", "skipped") else ""))
                    if detail:
                        ui.label(detail).classes("zp-xs zp-muted")
