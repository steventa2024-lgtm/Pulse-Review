from __future__ import annotations

from pathlib import Path

from nicegui import run, ui

from core import paths
from core.config import OLLAMA_BASE_URL
from core.github_client import GitHubError, InvalidPRUrl, parse_repo_name
from core.providers import ProviderError
from core.security import mask_secret

from ..components.layout import frame
from ..context import Ctx


def card(title: str, subtitle: str = ""):
    c = ui.element("div").classes("zp-card w-full")
    with c:
        ui.label(title).classes("text-lg font-semibold")
        if subtitle:
            ui.label(subtitle).classes("zp-muted text-sm mb-2")
    return c


def register(ctx: Ctx) -> None:
    @ui.page("/settings")
    def settings():
        svc, mgr = ctx.services, ctx.services.config_mgr

        def save(**kw) -> None:
            mgr.update(**kw)
            ctx.refresh_static()

        with frame(ctx, "settings"):
            ui.label("Settings").classes("text-2xl font-semibold")

            # ================================================================ GitHub
            with card("GitHub", "Use a fine-grained personal access token. Changes apply immediately."):
                ui.markdown("**Minimum permissions:** *Metadata: read*, *Contents: read*, *Pull requests: read*. "
                            "Publishing review comments additionally needs **Pull requests: write**. "
                            "Select only the repositories you want to review.")
                status = ui.label().classes("text-sm")
                token_in = ui.input("GitHub token", password=True, password_toggle_button=True,
                                    placeholder="github_pat_…").props("outlined dense").classes("w-full max-w-xl")
                detail = ui.column().classes("gap-0")

                def show_state() -> None:
                    tok = mgr.get_github_token()
                    status.set_text(f"Token stored ({mask_secret(tok)}) in {mgr.secrets.backend}." if tok else "No token configured.")
                    status.classes(replace="text-sm " + ("text-green-400" if tok else "text-amber-400"))

                async def test() -> None:
                    detail.clear()
                    try:
                        info = await run.io_bound(lambda: svc.github().test_connection())
                    except GitHubError as exc:
                        with detail:
                            ui.label(exc.message).classes("text-red-400 text-sm")
                        await run.io_bound(ctx.check_github)
                        return
                    with detail:
                        ui.label(f"Connected as {info.login}" + (f" ({info.name})" if info.name else "")).classes("text-green-400 text-sm")
                        if info.rate_remaining is not None:
                            ui.label(f"API rate limit: {info.rate_remaining}/{info.rate_limit} remaining").classes("zp-muted text-xs")
                    await run.io_bound(ctx.check_github)

                async def save_token() -> None:
                    if not (token_in.value or "").strip():
                        ui.notify("Paste a token first.", type="warning")
                        return
                    mgr.set_github_token(token_in.value)
                    token_in.set_value("")
                    show_state()
                    await test()

                def disconnect() -> None:
                    mgr.clear_github_token()
                    show_state()
                    detail.clear()
                    ctx.status.update(github_text="GitHub: not connected", github_ok=False)
                    ui.notify("GitHub token removed from this computer.")

                with ui.row().classes("gap-2"):
                    ui.button("Save connection", icon="save", on_click=save_token).props("unelevated color=primary")
                    ui.button("Test connection", icon="wifi_tethering", on_click=test).props("outline")
                    ui.button("Disconnect", icon="link_off", color="negative", on_click=disconnect).props("flat")
                show_state()
                ui.label("Repository access check").classes("zp-card-title mt-3")
                with ui.row().classes("items-center gap-2"):
                    repo_chk = ui.input("OWNER/REPO").props("outlined dense").classes("w-64")
                    repo_out = ui.label().classes("text-sm")

                    async def check_repo() -> None:
                        try:
                            o, r = parse_repo_name(repo_chk.value)
                            acc = await run.io_bound(lambda: svc.github().validate_repo_access(o, r))
                        except (InvalidPRUrl, GitHubError) as exc:
                            repo_out.set_text(getattr(exc, "message", str(exc)))
                            repo_out.classes(replace="text-sm text-red-400")
                            return
                        repo_out.set_text(f"{acc.full_name}: {'private' if acc.private else 'public'} • read OK • "
                                          f"{'write access (can publish reviews)' if acc.can_push else 'no write access reported (publishing may be refused)'}")
                        repo_out.classes(replace="text-sm text-green-400")

                    ui.button("Check", on_click=check_repo).props("outline dense")

            # ================================================================ AI provider
            with card("AI Provider", "Switch at any time — no restart needed."):
                prov = ui.toggle({"openrouter": "OpenRouter (free)", "ollama": "Local Ollama"}, value=svc.cfg.provider).props("no-caps unelevated")
                prov.on_value_change(lambda e: save(provider=e.value))

                ui.label("OpenRouter").classes("zp-card-title mt-4")
                or_state = ui.label().classes("text-sm")
                key_in = ui.input("OpenRouter API key", password=True, password_toggle_button=True, placeholder="sk-or-v1-…").props("outlined dense").classes("w-full max-w-xl")
                or_out = ui.column().classes("gap-0")
                or_model = ui.select({svc.cfg.openrouter.model: svc.cfg.openrouter.model}, value=svc.cfg.openrouter.model, label="Free model", with_input=True,
                                     new_value_mode="add-unique").props("outlined dense").classes("w-full max-w-xl")
                or_model.on_value_change(lambda e: e.value and save(openrouter={"model": e.value}))
                ui.label("Manual entry accepts any model id, but it is verified as zero-price against OpenRouter's live catalog before use. Paid models are refused.").classes("zp-muted text-xs")

                def or_show() -> None:
                    k = mgr.get_openrouter_key()
                    or_state.set_text(f"API key stored ({mask_secret(k)})." if k else "No API key configured.")
                    or_state.classes(replace="text-sm " + ("text-green-400" if k else "text-amber-400"))

                async def refresh_or() -> None:
                    or_out.clear()
                    try:
                        p = svc.provider("openrouter")
                        cands = await run.io_bound(lambda: p.candidate_status())
                        free = await run.io_bound(lambda: p.list_free_models(True))
                    except ProviderError as exc:
                        with or_out:
                            ui.label(exc.message).classes("text-red-400 text-sm")
                        return
                    opts = {}
                    for m in cands + [m for m in free if m.id not in {c.id for c in cands}]:
                        opts[m.id] = m.id + ("" if m.available else "  (currently unavailable)") + (f" • {m.context_length:,} ctx" if m.context_length else "")
                    cur = svc.cfg.openrouter.model
                    if cur not in opts:
                        opts[cur] = cur + "  (not verified free)"
                    or_model.set_options(opts, value=cur)
                    with or_out:
                        ui.label(f"{len(free)} free models available now.").classes("zp-muted text-xs")

                async def test_or() -> None:
                    or_out.clear()
                    try:
                        res = await run.io_bound(lambda: _probe(svc.provider("openrouter")))
                    except ProviderError as exc:
                        with or_out:
                            ui.label(f"{exc.kind}: {exc.message}").classes("text-red-400 text-sm")
                        return
                    with or_out:
                        ui.label(res).classes("text-green-400 text-sm")

                def save_key() -> None:
                    if key_in.value:
                        mgr.set_openrouter_key(key_in.value)
                        key_in.set_value("")
                        or_show()
                        ui.notify("OpenRouter key saved", type="positive")

                def clear_key() -> None:
                    mgr.clear_openrouter_key()
                    or_show()

                with ui.row().classes("gap-2"):
                    ui.button("Save key", icon="save", on_click=save_key).props("unelevated color=primary")
                    ui.button("Refresh model catalog", icon="refresh", on_click=refresh_or).props("outline")
                    ui.button("Test inference", icon="bolt", on_click=test_or).props("outline")
                    ui.button("Remove key", color="negative", on_click=clear_key).props("flat")
                or_show()
                ui.timer(0.2, refresh_or, once=True)

                ui.separator().classes("my-4")
                ui.label("Local Ollama").classes("zp-card-title")
                ol_out = ui.column().classes("gap-0")
                ol_url = ui.input("Endpoint", value=svc.cfg.ollama.base_url).props("outlined dense").classes("w-full max-w-xl")
                ol_url.on("blur", lambda: save(ollama={"base_url": ol_url.value or OLLAMA_BASE_URL}))
                ol_model = ui.select({svc.cfg.ollama.model: svc.cfg.ollama.model}, value=svc.cfg.ollama.model, label="Installed model", with_input=True,
                                     new_value_mode="add-unique").props("outlined dense").classes("w-full max-w-xl")
                ol_model.on_value_change(lambda e: e.value and save(ollama={"model": e.value}))
                with ui.row().classes("gap-4"):
                    ol_ctx = ui.number("Context length (tokens)", value=svc.cfg.ollama.context_length, min=2048, max=262144, step=1024, format="%.0f").props("outlined dense").classes("w-56")
                    ol_ctx.on_value_change(lambda e: e.value and save(ollama={"context_length": int(e.value)}))
                    ol_to = ui.number("Inference timeout (s)", value=svc.cfg.ollama.timeout, min=10, max=3600, step=30, format="%.0f").props("outlined dense").classes("w-56")
                    ol_to.on_value_change(lambda e: e.value and save(ollama={"timeout": float(e.value)}))
                ui.label("The 30B model may not fit entirely in 8 GB of VRAM; Ollama decides the GPU/CPU split. ZeroPulse never downloads or modifies models.").classes("zp-muted text-xs")

                async def refresh_ol() -> None:
                    ol_out.clear()
                    save(ollama={"base_url": ol_url.value or OLLAMA_BASE_URL})
                    try:
                        p = svc.provider("ollama")
                        h = await run.io_bound(p.health_check)
                        models = await run.io_bound(p.list_models) if h.detail.get("kind") != "unavailable" else []
                    except ProviderError as exc:
                        with ol_out:
                            ui.label(exc.message).classes("text-red-400 text-sm")
                        return
                    if models:
                        cur = svc.cfg.ollama.model
                        opts = {m.id: m.id for m in models}
                        opts.setdefault(cur, cur + " (not installed)")
                        ol_model.set_options(opts, value=cur)
                    with ol_out:
                        ui.label(h.message).classes("text-sm " + ("text-green-400" if h.ok else "text-amber-400"))

                async def test_ol() -> None:
                    ol_out.clear()
                    try:
                        res = await run.io_bound(lambda: _probe(svc.provider("ollama")))
                    except ProviderError as exc:
                        with ol_out:
                            ui.label(f"{exc.kind}: {exc.message}").classes("text-red-400 text-sm")
                        return
                    with ol_out:
                        ui.label(res).classes("text-green-400 text-sm")

                with ui.row().classes("gap-2"):
                    ui.button("Test local connection", icon="wifi_tethering", on_click=refresh_ol).props("outline")
                    ui.button("Test inference", icon="bolt", on_click=test_ol).props("outline")

            # ================================================================ Review
            r = svc.cfg.review
            with card("Review defaults"):
                with ui.row().classes("gap-4 items-center"):
                    d = ui.toggle({"quick": "Quick", "standard": "Standard", "deep": "Deep"}, value=r.depth).props("no-caps unelevated")
                    d.on_value_change(lambda e: save(review={"depth": e.value}))
                    mc = ui.number("Max context budget (tokens)", value=r.max_context_budget, min=2000, max=262144, step=1000, format="%.0f").props("outlined dense").classes("w-60")
                    mc.on_value_change(lambda e: e.value and save(review={"max_context_budget": int(e.value)}))
                    mf = ui.number("Max findings", value=r.max_findings, min=1, max=20, step=1, format="%.0f").props("outlined dense").classes("w-40")
                    mf.on_value_change(lambda e: e.value and save(review={"max_findings": int(e.value)}))
                for label, key in (("Generate test file by default", "generate_tests"), ("Security analysis", "security_analysis"),
                                   ("Performance analysis", "performance_analysis"), ("Run sandboxed tests by default (needs Docker)", "run_sandbox_tests")):
                    ui.switch(label, value=getattr(r, key), on_change=lambda e, k=key: save(review={k: bool(e.value)}))
                ui.switch("Always allow sending private-repository code to OpenRouter (otherwise asked per review)", value=svc.cfg.openrouter.private_repo_consent,
                          on_change=lambda e: save(openrouter={"private_repo_consent": bool(e.value)}))

            # ================================================================ Application
            a = svc.cfg.app
            with card("Application"):
                with ui.row().classes("gap-4 items-center"):
                    pm = ui.number("Watch polling interval (minutes, 0 = manual)", value=a.watch_poll_minutes, min=0, max=1440, step=5, format="%.0f").props("outlined dense").classes("w-80")
                    pm.on_value_change(lambda e: e.value is not None and save(app={"watch_poll_minutes": int(e.value)}))
                    ui.switch("Automatically analyse new/updated watched PRs (never posts)", value=a.auto_analyze_watched,
                              on_change=lambda e: save(app={"auto_analyze_watched": bool(e.value)}))
                dl = ui.input("Default download directory", value=a.download_dir, placeholder=str(Path.home() / "Downloads")).props("outlined dense").classes("w-full max-w-xl")
                dl.on("blur", lambda: save(app={"download_dir": dl.value or ""}))
                ui.label(f"Data folder: {paths.data_dir()}").classes("zp-mono zp-muted text-xs mt-2")

                def show_logs() -> None:
                    f = paths.logs_dir() / "app.log"
                    text = "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-200:]) if f.exists() else "No log file yet."
                    with ui.dialog() as dlg, ui.card().classes("zp-card w-[900px] max-w-full"):
                        ui.label(str(f)).classes("zp-mono zp-muted text-xs")
                        ui.code(text, language="text").classes("w-full max-h-[60vh] overflow-auto")
                        ui.button("Close", on_click=dlg.close).props("flat")
                    dlg.open()

                def wipe() -> None:
                    with ui.dialog() as dlg, ui.card().classes("zp-card"):
                        ui.label("Delete all stored PR content?").classes("text-lg")
                        ui.label("Removes reviews, findings, generated tests and publication records. Settings and secrets are kept.").classes("text-sm w-96")
                        with ui.row().classes("justify-end w-full"):
                            ui.button("Cancel", on_click=dlg.close).props("flat")
                            ui.button("Delete", color="negative", on_click=lambda: (svc.db.clear_pr_content(), dlg.close(), ui.notify("Stored PR content deleted", type="positive")))
                    dlg.open()

                with ui.row().classes("gap-2 mt-2"):
                    ui.button("View logs", icon="article", on_click=show_logs).props("outline")
                    ui.button("Delete stored PR content", icon="delete_sweep", color="negative", on_click=wipe).props("outline")


def _probe(provider) -> str:
    """Tiny real inference call to prove the model answers (free models cost nothing; Ollama is local)."""
    res = provider.generate([{"role": "user", "content": "Reply with the single word: OK"}], max_tokens=16)
    return f"{provider.model} answered: {res.text.strip()[:80]!r}"
