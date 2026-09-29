from __future__ import annotations

from nicegui import run, ui

from core.github_client import GitHubError, InvalidPRUrl, parse_pr_url
from core.providers import ProviderError
from core.review_pipeline import STEPS
from core.schemas import PRRef

from ..components.layout import frame
from ..components.widgets import pill
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/review/new")
    def new_review(url: str = ""):
        svc = ctx.services
        cfg = svc.cfg
        state = {"provider": cfg.provider, "preview_private": False, "job": None, "models": {}}

        with frame(ctx, "new"):
            ui.label("New Review").classes("text-2xl font-semibold")
            with ui.row().classes("w-full gap-4 items-start no-wrap max-lg:flex-wrap"):
                # ------------------------------------------------------------ left: form
                with ui.column().classes("gap-4 flex-1 min-w-[340px]"):
                    with ui.element("div").classes("zp-card w-full"):
                        ui.label("Pull request").classes("zp-card-title mb-2")
                        with ui.row().classes("w-full no-wrap items-start gap-2"):
                            url_in = ui.input("Pull-request URL", value=url, placeholder="https://github.com/OWNER/REPO/pull/123") \
                                .props("outlined dense clearable").classes("flex-1")
                            ui.button("Check", icon="search", on_click=lambda: check_pr()).props("outline")
                        preview = ui.column().classes("w-full gap-1 mt-2")

                    with ui.element("div").classes("zp-card w-full"):
                        ui.label("Model").classes("zp-card-title mb-2")
                        prov = ui.toggle({"openrouter": "OpenRouter (free)", "ollama": "Local Ollama"}, value=state["provider"]).props("no-caps unelevated")
                        model_sel = ui.select(options=[], label="Model", with_input=True).props("outlined dense").classes("w-full mt-2")
                        model_note = ui.label().classes("zp-muted text-xs")
                        manual = ui.input("Or enter a model id manually").props("outlined dense clearable").classes("w-full mt-2")
                        ui.button("Refresh models", icon="refresh", on_click=lambda: load_models(True)).props("flat dense no-caps")

                    with ui.element("div").classes("zp-card w-full"):
                        ui.label("Options").classes("zp-card-title mb-2")
                        depth = ui.toggle({"quick": "Quick", "standard": "Standard", "deep": "Deep"}, value=cfg.review.depth).props("no-caps unelevated")
                        ui.label("Quick: 1 model call • Standard: up to 6 • Deep: up to 20 (large PRs)").classes("zp-muted text-xs mb-2")
                        gen = ui.checkbox("Generate test file", value=cfg.review.generate_tests)
                        sandbox = ui.checkbox("Run sandboxed tests (Docker)", value=cfg.review.run_sandbox_tests)
                        sb_note = ui.label().classes("zp-muted text-xs ml-8")
                        sb_install = ui.checkbox("Install dependencies in the sandbox (network on during install only)").classes("ml-6")
                        sb_pull = ui.checkbox("Allow Docker to download the base image if missing").classes("ml-6")
                        sec = ui.checkbox("Include security analysis", value=cfg.review.security_analysis)
                        perf = ui.checkbox("Include performance analysis", value=cfg.review.performance_analysis)
                        consent = ui.checkbox("I consent to sending this PRIVATE repository's code to the hosted provider (OpenRouter)",
                                              value=cfg.openrouter.private_repo_consent).classes("text-amber-400")
                        consent.set_visibility(False)

                        def sync_sandbox() -> None:
                            ok = bool(ctx.status.get("docker_ok"))
                            sandbox.set_enabled(ok and gen.value)
                            if not ok:
                                sandbox.value = False
                            sb_note.set_text("" if ok else "Sandbox unavailable — generated test has not been executed.")
                            sb_install.set_visibility(bool(sandbox.value))
                            sb_pull.set_visibility(bool(sandbox.value))

                        sandbox.on_value_change(lambda _: sync_sandbox())
                        gen.on_value_change(lambda _: sync_sandbox())
                        ui.timer(2.0, sync_sandbox)
                        sync_sandbox()

                    start_btn = ui.button("START REVIEW", icon="play_arrow", on_click=lambda: start()).props("unelevated color=primary size=lg").classes("w-full")

                # ------------------------------------------------------------ right: progress
                with ui.column().classes("gap-4 w-[420px] max-lg:w-full"):
                    with ui.element("div").classes("zp-card w-full"):
                        ui.label("Pipeline progress").classes("zp-card-title mb-2")
                        steps_box = ui.column().classes("w-full gap-0")
                        result_box = ui.column().classes("w-full mt-3 gap-2")
                        cancel_btn = ui.button("Cancel review", icon="stop", color="negative", on_click=lambda: cancel()).props("outline").classes("mt-2")
                        cancel_btn.set_visibility(False)
                    draw_steps({k: ("pending", "") for k, _ in STEPS}, steps_box)

            # ---------------------------------------------------------------- behaviour
            def cur_model() -> str | None:
                return (manual.value or "").strip() or model_sel.value or None

            async def load_models(force: bool = False) -> None:
                p = prov.value
                model_note.set_text("Loading…")
                try:
                    provider = svc.provider(p)
                    if p == "openrouter":
                        models = await run.io_bound(lambda: provider.candidate_status() + [m for m in provider.list_free_models(force) if m.id not in {c.id for c in provider.candidate_status()}])
                        opts = {m.id: (m.id + ("" if m.available else "  (unavailable)") + (f"  • {m.context_length:,} ctx" if m.context_length else "")) for m in models}
                        current = cfg.openrouter.model
                        model_note.set_text("Only verified zero-price models are listed; paid models are never used.")
                    else:
                        models = await run.io_bound(provider.list_models)
                        opts = {m.id: m.id for m in models}
                        current = cfg.ollama.model
                        model_note.set_text("Installed Ollama models. ZeroPulse never downloads models for you.")
                    model_sel.set_options(opts, value=current if current in opts else (next(iter(opts), None)))
                except (ProviderError, GitHubError) as exc:
                    # keep the saved choice selectable but clearly unverified; generate() still refuses unverified models
                    saved = cfg.openrouter.model if prov.value == "openrouter" else cfg.ollama.model
                    model_sel.set_options({saved: f"{saved}  (unverified — offline)"}, value=saved)
                    model_note.set_text(getattr(exc, "message", str(exc)))
                except Exception as exc:  # noqa: BLE001
                    model_note.set_text(f"Could not load models: {exc}")
                update_consent()

            def update_consent() -> None:
                consent.set_visibility(prov.value == "openrouter" and state["preview_private"])

            prov.on_value_change(lambda _: (load_models(), update_consent()))

            async def check_pr() -> None:
                preview.clear()
                try:
                    ref = parse_pr_url(url_in.value)
                except InvalidPRUrl as exc:
                    with preview:
                        ui.label(str(exc)).classes("text-red-400 text-sm")
                    return
                with preview:
                    ui.label("Contacting GitHub…").classes("zp-muted text-sm")
                try:
                    data = await run.io_bound(lambda: svc.github().fetch_pr(ref))
                except GitHubError as exc:
                    preview.clear()
                    with preview:
                        ui.label(exc.message).classes("text-red-400 text-sm")
                    return
                state["preview_private"] = data.private
                preview.clear()
                with preview:
                    with ui.row().classes("items-center gap-2"):
                        ui.label(f"{data.ref.full_name} #{data.ref.number}").classes("font-semibold")
                        pill("private", "medium") if data.private else pill("public", "gray")
                        pill(data.state, "ok" if data.state == "open" else "gray")
                    ui.label(data.title).classes("text-sm")  # plain text: title is untrusted
                    ui.label(f"by {data.author} • {data.base_ref} ← {data.head_ref} • {len(data.files)} files "
                             f"(+{sum(f.additions for f in data.files)} / -{sum(f.deletions for f in data.files)})").classes("zp-muted text-xs")
                    for lim in data.limitations:
                        ui.label("⚠ " + lim).classes("text-amber-400 text-xs")
                    if data.private and prov.value == "openrouter":
                        ui.label("Private repository: source code would be sent to OpenRouter. Consent is required below, or switch to local Ollama.").classes("text-amber-400 text-xs")
                update_consent()

            def render_steps(job) -> None:
                draw_steps(job.steps, steps_box)

            def cancel() -> None:
                job = state["job"]
                if job and not job.done:
                    job.cancel.set()
                    ui.notify("Cancelling after the current step…")

            async def start() -> None:
                try:
                    ref: PRRef = parse_pr_url(url_in.value)
                except InvalidPRUrl as exc:
                    ui.notify(str(exc), type="negative")
                    return
                if not svc.config_mgr.get_github_token():
                    ui.notify("Connect GitHub first (Settings → GitHub).", type="warning")
                    return
                p = prov.value
                if p == "openrouter" and not svc.config_mgr.get_openrouter_key():
                    ui.notify("Add your OpenRouter API key in Settings → AI Provider.", type="warning")
                    return
                model = cur_model()
                if not model:
                    ui.notify("Select or enter a model.", type="warning")
                    return
                opts = svc.review_options(depth=depth.value, generate_tests=bool(gen.value), run_sandbox=bool(sandbox.value and gen.value),
                                          security=bool(sec.value), performance=bool(perf.value),
                                          private_hosted_consent=bool(consent.value))
                opts.sandbox_install_deps, opts.sandbox_allow_pull = bool(sb_install.value), bool(sb_pull.value)
                # persist the user's model choice so it is the default next time (no restart needed)
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
                timer = ui.timer(0.4, lambda: tick(job))
                state["timer"] = timer

            def tick(job) -> None:
                render_steps(job)
                if not job.done:
                    return
                state["timer"].deactivate()
                start_btn.enable()
                cancel_btn.set_visibility(False)
                result_box.clear()
                with result_box:
                    if job.error:
                        color = "text-amber-400" if job.error_kind in ("consent", "cancelled") else "text-red-400"
                        ui.label(job.error).classes(f"{color} text-sm")
                        if job.review_id:
                            ui.button("View record", on_click=lambda: ui.navigate.to(f"/review/{job.review_id}")).props("flat dense")
                    else:
                        ui.label("Review complete.").classes("text-green-400")
                        ui.button("Open review", icon="open_in_new", on_click=lambda: ui.navigate.to(f"/review/{job.review_id}")).props("unelevated color=primary")
                        ui.navigate.to(f"/review/{job.review_id}")

            ui.timer(0.1, lambda: load_models(), once=True)
            if url:
                ui.timer(0.3, lambda: check_pr(), once=True)


def draw_steps(steps: dict[str, tuple[str, str]], box) -> None:
    box.clear()
    with box:
        for key, label in STEPS:
            state, detail = steps.get(key, ("pending", ""))
            with ui.element("div").classes("zp-step"):
                if state == "running":
                    ui.spinner(size="18px")
                else:
                    icon, color = {"done": ("check_circle", "text-green-400"), "failed": ("error", "text-red-400"),
                                   "skipped": ("remove_circle_outline", "zp-muted"), "pending": ("radio_button_unchecked", "zp-muted")}[state]
                    ui.icon(icon, size="18px").classes(color)
                with ui.column().classes("gap-0"):
                    ui.label(label).classes("text-sm" + (" zp-muted" if state in ("pending", "skipped") else ""))
                    if detail:
                        ui.label(detail).classes("zp-muted text-xs")
