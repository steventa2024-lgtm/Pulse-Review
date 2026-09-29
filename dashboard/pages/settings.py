from __future__ import annotations

import threading
from pathlib import Path

from dashboard.components.external import open_external
from nicegui import run, ui

from core import paths
from core.config import OLLAMA_BASE_URL
from core.github_client import GitHubError, InvalidPRUrl, parse_repo_name
from core.github_oauth import DeviceFlow, OAuthError, save_token, scopes_for
from core.providers import ProviderError
from core.security import mask_secret

from ..components.kit import (btn, callout, card, field, fmt_ctx, page_header, segmented, select, setting,
                              text_input)
from ..components.layout import frame
from ..context import Ctx

OAUTH_APP_URL = "https://github.com/settings/applications/new"


def model_options(models, current: str | None) -> dict[str, str]:
    opts: dict[str, str] = {}
    for m in models:
        parts = [m.id]
        if m.context_length:
            parts.append(fmt_ctx(m.context_length))
        if m.recommended:
            parts.append("★ recommended")
        opts[m.id] = "  ·  ".join(parts)
    if current and current not in opts:
        opts[current] = f"{current}  ·  not in the current free catalog"
    return opts


def register(ctx: Ctx) -> None:
    @ui.page("/settings")
    def settings(tab: str = "github"):
        svc, mgr = ctx.services, ctx.services.config_mgr

        def save(**kw) -> None:
            mgr.update(**kw)
            ctx.refresh_static()

        with frame(ctx, "settings"):
            page_header("Settings", "Changes are saved immediately. No restart needed.")
            with ui.tabs(value=tab).classes("zp-tabs w-full").props("align=left no-caps inline-label dense active-color=white indicator-color=primary") as tabs:
                ui.tab("github", "GitHub", icon="hub")
                ui.tab("ai", "AI models", icon="auto_awesome")
                ui.tab("review", "Review", icon="rule")
                ui.tab("app", "Application", icon="tune")
            with ui.tab_panels(tabs, value=tab).classes("w-full").props("animated=false"):
                with ui.tab_panel("github"):
                    github_panel(ctx, save)
                with ui.tab_panel("ai"):
                    ai_panel(ctx, save)
                with ui.tab_panel("review"):
                    review_panel(ctx, save)
                with ui.tab_panel("app"):
                    app_panel(ctx, save)


# ============================================================================================ GitHub
def github_panel(ctx: Ctx, save) -> None:
    svc, mgr = ctx.services, ctx.services.config_mgr
    with card():
        with setting("Account", "ZeroPulse reads pull requests and, only when you confirm, posts review comments."):
            account = ui.column().classes("w-full gap-3")
        with setting("Repository access", "Private repositories need the broader “repo” permission."):
            priv = ui.checkbox("Include private repositories", value=mgr.config.github.include_private_repos,
                               on_change=lambda e: save(github={"include_private_repos": bool(e.value)}))
            ui.label("Takes effect the next time you sign in.").classes("zp-hint")
        with setting("Check a repository", "Confirms the connected account can read it and whether it can publish reviews."):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                repo_chk = text_input("owner/repo", classes="w-72")
                chk_btn = btn("Check", kind="secondary")
            repo_out = ui.column().classes("w-full")

    with card("Sign-in setup", "One-time: GitHub sign-in needs the Client ID of an OAuth App you own (it's public, not a secret)."):
        with ui.expansion("How to create it (about a minute)").classes("w-full").props("dense"):
            ui.markdown(
                f"1. Open **[New OAuth App]({OAUTH_APP_URL})** on GitHub.\n"
                "2. Application name: `ZeroPulse PR Review` · Homepage URL: `http://127.0.0.1` · Callback URL: `http://127.0.0.1`\n"
                "3. Tick **Enable Device Flow**, then **Register application**.\n"
                "4. Copy the **Client ID** (looks like `Ov23li…`) and paste it below. No client secret is needed.")
        with field("OAuth Client ID"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                cid = text_input("Ov23li…", value=mgr.config.github.oauth_client_id, classes="w-96")
                btn("Save", kind="secondary", on_click=lambda: (save(github={"oauth_client_id": (cid.value or "").strip()}),
                                                              ui.notify("Client ID saved", type="positive"), draw_account()))

    with card("Personal access token", "Alternative to signing in, e.g. for fine-grained per-repository tokens."):
        with ui.row().classes("items-center gap-2 no-wrap w-full"):
            pat = text_input("github_pat_…", password=True, classes="w-96")

            async def save_pat() -> None:
                if not (pat.value or "").strip():
                    ui.notify("Paste a token first.", type="warning")
                    return
                mgr.set_github_token(pat.value)
                pat.set_value("")
                await refresh_account()

            btn("Use token", "key", save_pat, kind="secondary")
        ui.label("Fine-grained token permissions: Metadata, Contents and Pull requests (read). Add Pull requests (write) to publish.").classes("zp-hint")

    state = {"info": None, "error": None}

    def draw_account() -> None:
        account.clear()
        tok = mgr.get_github_token()
        with account:
            info, err = state["info"], state["error"]
            if tok and info:
                with ui.row().classes("items-center gap-3 no-wrap"):
                    if info.avatar_url:
                        ui.image(info.avatar_url).classes("w-10 h-10 rounded-full")
                    with ui.column().classes("gap-0"):
                        ui.label(info.name or info.login).classes("zp-h3")
                        how = {"oauth": "GitHub sign-in", "pat": "personal access token"}.get(mgr.config.github.auth_method, "token from environment")
                        ui.label(f"@{info.login} · connected via {how}" + (f" · scopes: {info.scopes}" if info.scopes else "")).classes("zp-sub zp-small")
                with ui.row().classes("gap-2"):
                    btn("Sign out", "logout", sign_out, kind="secondary")
                    btn("Re-check", "refresh", refresh_account, kind="ghost")
            elif tok and err:
                callout(err, "err")
                with ui.row().classes("gap-2"):
                    btn("Sign in again", "login", start_sign_in, kind="primary")
                    btn("Sign out", "logout", sign_out, kind="ghost")
            elif tok:
                ui.label("Checking connection…").classes("zp-sub")
            else:
                ui.label("Not connected.").classes("zp-sub")
                b = btn("Sign in with GitHub", "login", start_sign_in, kind="primary", size="lg")
                if not mgr.effective_oauth_client_id():
                    b.disable()
                    callout("Complete the one-time sign-in setup below first, or use a personal access token.", "info")

    async def refresh_account() -> None:
        state["info"], state["error"] = None, None
        draw_account()
        if mgr.get_github_token():
            try:
                state["info"] = await run.io_bound(lambda: svc.github().test_connection())
            except GitHubError as exc:
                state["error"] = exc.message
        draw_account()
        await run.io_bound(ctx.check_github)

    def sign_out() -> None:
        mgr.clear_github_token()
        state["info"] = state["error"] = None
        ctx.status.update(github_text="GitHub · not connected", github_ok=False)
        draw_account()
        ui.notify("Signed out. The token was removed from this computer.")

    async def start_sign_in() -> None:
        try:
            flow = DeviceFlow(mgr.effective_oauth_client_id(), mgr.config.github.web_base_url)
            code = await run.io_bound(lambda: flow.start(scopes_for(bool(priv.value))))
        except OAuthError as exc:
            ui.notify(exc.message, type="negative", multi_line=True)
            return
        cancel = threading.Event()
        with ui.dialog().props("persistent") as d, ui.card().classes("zp-card w-[460px] items-center gap-4"):
            ui.label("Sign in with GitHub").classes("zp-h2 self-start")
            ui.label("Enter this code on GitHub to authorize ZeroPulse:").classes("zp-sub self-start")
            ui.label(code.user_code).classes("zp-code w-full")

            def open_github() -> None:
                ui.clipboard.write(code.user_code)
                open_external(code.verification_uri)

            btn("Copy code & open GitHub", "open_in_new", open_github, kind="primary", size="lg").classes("w-full")
            with ui.row().classes("items-center gap-2 self-start"):
                ui.spinner(size="16px")
                status = ui.label("Waiting for you to approve on GitHub…").classes("zp-sub zp-small")
            with ui.row().classes("justify-end w-full"):
                btn("Cancel", on_click=lambda: (cancel.set(), d.close()), kind="ghost")
        d.open()
        open_github()
        try:
            tok = await run.io_bound(lambda: flow.wait(code, cancel))
        except OAuthError as exc:
            if not cancel.is_set():
                status.set_text(exc.message)
                ui.notify(exc.message, type="negative")
            return
        save_token(mgr, tok)
        d.close()
        ui.notify("Signed in to GitHub", type="positive")
        await refresh_account()

    async def check_repo() -> None:
        repo_out.clear()
        try:
            o, r = parse_repo_name(repo_chk.value)
            acc = await run.io_bound(lambda: svc.github().validate_repo_access(o, r))
        except (InvalidPRUrl, GitHubError) as exc:
            with repo_out:
                callout(getattr(exc, "message", str(exc)), "err")
            return
        with repo_out:
            callout(f"{acc.full_name} ({'private' if acc.private else 'public'}): readable. "
                    + ("Write access — reviews can be published." if acc.can_push else "No write access — publishing may be refused."),
                    "ok" if acc.can_push else "warn")

    chk_btn.on_click(check_repo)
    draw_account()
    ui.timer(0.1, refresh_account, once=True)


# ============================================================================================ AI
def ai_panel(ctx: Ctx, save) -> None:
    svc, mgr = ctx.services, ctx.services.config_mgr
    with card():
        with setting("Provider", "Where reviews run. Switching needs no restart; the review logic is identical."):
            segmented({"openrouter": "OpenRouter (free cloud models)", "ollama": "Ollama (local)"}, svc.cfg.provider,
                      on_change=lambda e: save(provider=e.value))

    # ---------------------------------------------------------------- OpenRouter
    with card("OpenRouter", "Only models that OpenRouter currently lists at $0 are offered — paid models are never used."):
        with setting("API key", "Free account at openrouter.ai → Keys. Stored encrypted for your Windows user."):
            key_state = ui.label().classes("zp-small")
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                key_in = text_input("sk-or-v1-…", password=True, classes="w-96")
                btn("Save", kind="secondary", on_click=lambda: save_key())
                btn("Remove", kind="danger", on_click=lambda: clear_key())
        with setting("Model", "Code-focused models are listed first. You can also type any free model id."):
            or_model = select({}, classes="w-full max-w-[560px]", with_input=True, new_values=True)
            or_note = ui.label().classes("zp-hint")
            with ui.row().classes("gap-2"):
                btn("Refresh list", "refresh", lambda: refresh_or(True), kind="secondary")
                btn("Test model", "bolt", lambda: test_model("openrouter", or_out), kind="secondary")
            or_out = ui.column().classes("w-full")

    def key_show() -> None:
        k = mgr.get_openrouter_key()
        key_state.set_text(f"Key saved ({mask_secret(k)})" if k else "No key saved yet")
        key_state.classes(replace="zp-small " + ("zp-ok" if k else "zp-warn"))

    def save_key() -> None:
        if key_in.value:
            mgr.set_openrouter_key(key_in.value)
            key_in.set_value("")
            key_show()
            ui.notify("OpenRouter key saved", type="positive")

    def clear_key() -> None:
        mgr.clear_openrouter_key()
        key_show()

    guard = {"loading": False}

    async def refresh_or(force: bool = False) -> None:
        guard["loading"] = True
        or_note.set_text("Loading the live model catalog…")
        try:
            p = svc.provider("openrouter")
            models = await run.io_bound(lambda: p.review_models(force))
        except ProviderError as exc:
            or_note.set_text(exc.message)
            guard["loading"] = False
            return
        cur = svc.cfg.openrouter.model
        or_model.set_options(model_options(models, cur), value=cur)
        ids = {m.id for m in models}
        if cur not in ids and models:
            or_note.set_text(f"“{cur}” is no longer offered for free. Pick another model — ★ marks the best matches for code review.")
            or_note.classes(replace="zp-hint zp-warn")
        else:
            or_note.set_text(f"{len(models)} free models suitable for code review right now.")
            or_note.classes(replace="zp-hint")
        guard["loading"] = False

    def on_or_model(e) -> None:
        if e.value and not guard["loading"] and e.value != svc.cfg.openrouter.model:
            save(openrouter={"model": e.value})
            or_note.set_text(f"Using {e.value}.")
            or_note.classes(replace="zp-hint")

    or_model.on_value_change(on_or_model)

    # ---------------------------------------------------------------- Ollama
    with card("Ollama", "Runs entirely on this PC. ZeroPulse never downloads or changes your models."):
        with setting("Server", "Default: http://localhost:11434/v1"):
            with ui.row().classes("items-center gap-2 no-wrap w-full"):
                ol_url = text_input(OLLAMA_BASE_URL, value=svc.cfg.ollama.base_url, classes="w-96")
                btn("Connect", "link", lambda: refresh_ol(), kind="secondary")
            ol_status = ui.column().classes("w-full")
        with setting("Model", "Installed models only. Install others with: ollama pull <name>"):
            ol_model = select({svc.cfg.ollama.model: svc.cfg.ollama.model}, value=svc.cfg.ollama.model, classes="w-full max-w-[560px]",
                              with_input=True, new_values=True)
            ol_model.on_value_change(lambda e: e.value and save(ollama={"model": e.value}))
            btn("Test model", "bolt", lambda: test_model("ollama", ol_out), kind="secondary").classes("self-start")
            ol_out = ui.column().classes("w-full")
        with setting("Performance", "Larger context lets the model see more code per call but needs more memory. "
                                    "Big models may not fit entirely in 8 GB VRAM — Ollama splits GPU/CPU automatically."):
            with ui.row().classes("gap-4"):
                with field("Context length (tokens)", classes="w-56"):
                    ui.number(value=svc.cfg.ollama.context_length, min=2048, max=262144, step=1024, format="%.0f",
                              on_change=lambda e: e.value and save(ollama={"context_length": int(e.value)})).props("outlined dense hide-bottom-space")
                with field("Timeout per call (seconds)", classes="w-56"):
                    ui.number(value=svc.cfg.ollama.timeout, min=10, max=3600, step=30, format="%.0f",
                              on_change=lambda e: e.value and save(ollama={"timeout": float(e.value)})).props("outlined dense hide-bottom-space")

    async def refresh_ol() -> None:
        save(ollama={"base_url": (ol_url.value or OLLAMA_BASE_URL).strip()})
        ol_status.clear()
        try:
            p = svc.provider("ollama")
            h = await run.io_bound(p.health_check)
            models = await run.io_bound(p.list_models) if h.detail.get("kind") not in ("unavailable", "timeout") else []
        except ProviderError as exc:
            with ol_status:
                callout(exc.message, "err")
            return
        if models:
            cur = svc.cfg.ollama.model
            opts = {m.id: m.id for m in models}
            if cur not in opts:
                opts[cur] = f"{cur}  ·  not installed"
            ol_model.set_options(opts, value=cur)
        with ol_status:
            callout(h.message, "ok" if h.ok else "warn")

    async def test_model(which: str, out) -> None:
        out.clear()
        with out:
            with ui.row().classes("items-center gap-2"):
                ui.spinner(size="16px")
                ui.label("Asking the model to reply…").classes("zp-sub zp-small")
        try:
            res = await run.io_bound(lambda: _probe(svc.provider(which)))
        except ProviderError as exc:
            out.clear()
            with out:
                callout(exc.message, "err")
            return
        out.clear()
        with out:
            callout(res, "ok")

    key_show()
    ui.timer(0.1, refresh_or, once=True)
    ui.timer(0.2, refresh_ol, once=True)


# ============================================================================================ Review
def review_panel(ctx: Ctx, save) -> None:
    r = ctx.services.cfg.review
    with card():
        with setting("Depth", "Quick: 1 model call · Standard: up to 6 · Deep: up to 20 plus full-file context (large PRs)."):
            segmented({"quick": "Quick", "standard": "Standard", "deep": "Deep"}, r.depth, on_change=lambda e: save(review={"depth": e.value}))
        with setting("Limits", "The context budget is capped by the model's real context window."):
            with ui.row().classes("gap-4"):
                with field("Context budget (tokens)", classes="w-56"):
                    ui.number(value=r.max_context_budget, min=2000, max=262144, step=1000, format="%.0f",
                              on_change=lambda e: e.value and save(review={"max_context_budget": int(e.value)})).props("outlined dense hide-bottom-space")
                with field("Max findings", classes="w-40"):
                    ui.number(value=r.max_findings, min=1, max=20, step=1, format="%.0f",
                              on_change=lambda e: e.value and save(review={"max_findings": int(e.value)})).props("outlined dense hide-bottom-space")
        with setting("Defaults for new reviews"):
            for label, key in (("Generate a test file", "generate_tests"), ("Security analysis", "security_analysis"),
                               ("Performance analysis", "performance_analysis"), ("Run generated tests in the Docker sandbox", "run_sandbox_tests")):
                ui.switch(label, value=getattr(r, key), on_change=lambda e, k=key: save(review={k: bool(e.value)}))
        with setting("Private repositories", "Private code sent to OpenRouter leaves your PC. Otherwise you are asked on each review. Ollama is never affected."):
            ui.switch("Always allow sending private code to OpenRouter", value=ctx.services.cfg.openrouter.private_repo_consent,
                      on_change=lambda e: save(openrouter={"private_repo_consent": bool(e.value)}))


# ============================================================================================ Application
def app_panel(ctx: Ctx, save) -> None:
    svc = ctx.services
    a = svc.cfg.app
    with card():
        with setting("Test sandbox", "Generated tests only ever run inside an isolated Docker container (no network, no access to your files)."):
            sb = ui.column().classes("w-full gap-2")

            async def recheck() -> None:
                sb.clear()
                with sb:
                    with ui.row().classes("items-center gap-2"):
                        ui.spinner(size="16px")
                        ui.label("Checking Docker…").classes("zp-sub zp-small")
                await run.io_bound(ctx.check_local_services)
                sb.clear()
                with sb:
                    if ctx.status.get("docker_ok"):
                        callout("Docker Desktop is running with Linux containers. Sandbox is ready.", "ok")
                    else:
                        callout(str(ctx.status.get("docker_reason")), "warn")
                        ui.markdown("Install **[Docker Desktop](https://www.docker.com/products/docker-desktop/)**, start it, and wait for "
                                    "“Engine running”. Then press *Check again*. Tip: run `docker pull python:3.11-slim` once.").classes("zp-small")
                    btn("Check again", "refresh", recheck, kind="secondary").classes("self-start")

            ui.timer(0.1, recheck, once=True)
        with setting("Watched repositories", "Polling only — no server is exposed. Analysis can run automatically; publishing never does."):
            with field("Check every (minutes, 0 = manual)", classes="w-64"):
                ui.number(value=a.watch_poll_minutes, min=0, max=1440, step=5, format="%.0f",
                          on_change=lambda e: e.value is not None and save(app={"watch_poll_minutes": int(e.value)})).props("outlined dense hide-bottom-space")
            ui.switch("Analyse new or updated PRs automatically", value=a.auto_analyze_watched,
                      on_change=lambda e: save(app={"auto_analyze_watched": bool(e.value)}))
        with setting("Downloads", "Where “Save locally” writes generated tests."):
            dl = text_input(str(Path.home() / "Downloads"), value=a.download_dir, classes="w-full max-w-[560px]")
            dl.on("blur", lambda: save(app={"download_dir": dl.value or ""}))
        with setting("Data & logs", str(paths.data_dir())):
            with ui.row().classes("gap-2"):
                btn("View logs", "article", show_logs, kind="secondary")
                btn("Delete stored review data", "delete_sweep", lambda: wipe(svc), kind="danger")


def show_logs() -> None:
    f = paths.logs_dir() / "app.log"
    text = "\n".join(f.read_text(encoding="utf-8", errors="replace").splitlines()[-300:]) if f.exists() else "No log file yet."
    with ui.dialog() as dlg, ui.card().classes("zp-card w-[960px] max-w-full"):
        ui.label(str(f)).classes("zp-mono zp-muted")
        ui.code(text, language="text").classes("w-full max-h-[60vh] overflow-auto")
        with ui.row().classes("justify-end w-full"):
            btn("Close", on_click=dlg.close, kind="ghost")
    dlg.open()


def wipe(svc) -> None:
    with ui.dialog() as dlg, ui.card().classes("zp-card w-[440px]"):
        ui.label("Delete stored review data?").classes("zp-h2")
        ui.label("Removes all reviews, findings, generated tests and publication records from this PC. "
                 "Settings, sign-in and watched repositories are kept. Nothing on GitHub changes.").classes("zp-sub")
        with ui.row().classes("justify-end w-full gap-2 mt-2"):
            btn("Cancel", on_click=dlg.close, kind="ghost")
            btn("Delete", kind="danger-solid", on_click=lambda: (svc.db.clear_pr_content(), dlg.close(), ui.notify("Review data deleted", type="positive")))
    dlg.open()


def _probe(provider) -> str:
    """Tiny real inference call (free model or local) to prove the model answers."""
    res = provider.generate([{"role": "user", "content": "Reply with the single word: OK"}], max_tokens=16)
    return f"{provider.model} replied: “{res.text.strip()[:60]}”"
