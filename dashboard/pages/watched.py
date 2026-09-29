from __future__ import annotations

from nicegui import run, ui

from core.github_client import GitHubError, InvalidPRUrl

from ..components.kit import empty_state, btn, card, page_header, select, text_input
from ..components.layout import frame
from ..components.widgets import fmt_time, pill
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/watch")
    def watched():
        svc = ctx.services
        with frame(ctx, "watch"):
            actions = page_header("Watched repositories", "New and updated pull requests, checked by polling. Publishing always stays manual.")
            with actions:
                btn("Refresh all", "refresh", lambda: refresh(None), kind="secondary")

            with card("Add a repository"):
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    repo_in = text_input("owner/repo  (e.g. octocat/hello-world)", classes="flex-1")
                    btn("Watch", "add", lambda: add(repo_in.value), kind="primary")
                with ui.row().classes("items-center gap-2 w-full no-wrap"):
                    picker = select([], classes="flex-1", with_input=True).props('placeholder="…or choose from repositories you can access"')
                    btn("Load my repositories", "cloud_download", lambda: load_repos(), kind="secondary")
                    picker.on_value_change(lambda e: repo_in.set_value(e.value) if e.value else None)
                poll = svc.cfg.app.watch_poll_minutes
                ui.label("Automatic checks: " + (f"every {poll} min" if poll else "off — press Refresh") + " · change in Settings → Application").classes("zp-hint")

            board = ui.column().classes("w-full gap-3")

            async def load_repos() -> None:
                try:
                    repos = await run.io_bound(lambda: svc.github().list_accessible_repos(100))
                except GitHubError as exc:
                    ui.notify(exc.message, type="negative")
                    return
                picker.set_options(repos)
                if not repos:
                    ui.notify("No repositories returned. Connect GitHub in Settings.", type="warning")

            async def add(name: str) -> None:
                try:
                    full = await run.io_bound(lambda: svc.watcher().add_repo(name))
                except (GitHubError, InvalidPRUrl) as exc:
                    ui.notify(getattr(exc, "message", str(exc)), type="negative")
                    return
                ui.notify(f"Now watching {full}", type="positive")
                repo_in.set_value("")
                await refresh(full)

            async def refresh(repo: str | None) -> None:
                w = svc.watcher()
                try:
                    if repo:
                        results = [await run.io_bound(lambda: w.refresh(repo))]
                    else:
                        results = await run.io_bound(w.refresh_all)
                except GitHubError as exc:
                    ui.notify(exc.message, type="negative")
                    return
                summary = ", ".join(f"{r.repo}: {'unchanged' if r.not_modified else f'{r.new} new, {r.updated} updated'}" for r in results)
                if summary:
                    ui.notify(summary, type="info")
                draw()

            def remove(repo: str) -> None:
                svc.db.remove_watched_repo(repo)
                draw()

            def draw() -> None:
                board.clear()
                repos = svc.db.list_watched_repos()
                with board:
                    if not repos:
                        with ui.element("div").classes("zp-card w-full"):
                            empty_state("visibility", "No repositories watched yet", "Add one above to see its open pull requests here.")
                    for r in repos:
                        prs = svc.db.list_watched_prs(r["repo"])
                        with ui.element("div").classes("zp-card w-full"):
                            with ui.row().classes("items-center justify-between w-full"):
                                with ui.column().classes("gap-0"):
                                    ui.label(r["repo"]).classes("zp-h3")
                                    ui.label(f"Last checked: {fmt_time(r['last_checked'])} • {len(prs)} open PR(s)").classes("zp-muted zp-xs")
                                with ui.row().classes("gap-1"):
                                    ui.button("Refresh", icon="refresh", on_click=lambda repo=r["repo"]: refresh(repo), color=None).props("flat no-caps").classes("zp-btn-ghost")
                                    ui.button("Stop watching", icon="visibility_off", on_click=lambda repo=r["repo"]: remove(repo), color=None).props("flat no-caps").classes("zp-btn-danger")
                            if not r["last_checked"]:
                                ui.label("Not checked yet — press Refresh.").classes("zp-muted zp-small")
                            for pr in prs:
                                reviewed = pr["reviewed_sha"] == pr["head_sha"] or pr["head_sha"] in svc.db.reviewed_shas(r["repo"], pr["pr_number"])
                                with ui.row().classes("items-center gap-3 w-full py-1 no-wrap").style("border-top:1px solid var(--zp-border-soft)"):
                                    ui.label(f"#{pr['pr_number']}").classes("zp-mono zp-muted w-14")
                                    ui.label(pr["title"]).classes("flex-1 zp-small")  # plain text (untrusted)
                                    ui.label(pr["author"]).classes("zp-muted zp-xs w-28")
                                    if pr["indicator"] == "new":
                                        pill("NEW", "low")
                                    elif pr["indicator"] == "updated":
                                        pill("UPDATED", "medium")
                                    pill("reviewed" if reviewed else "not reviewed", "ok" if reviewed else "gray")
                                    ui.button("Review now", icon="play_arrow", on_click=lambda url=pr["url"]: ui.navigate.to(f"/review/new?url={url}")).props("unelevated no-caps color=primary").classes("zp-btn-sm")

            draw()
