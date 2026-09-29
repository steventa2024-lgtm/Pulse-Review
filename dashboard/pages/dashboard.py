from __future__ import annotations

from nicegui import ui

from ..components.kit import btn, card, empty_state, page_header
from ..components.layout import frame
from ..components.tables import reviews_table
from ..components.widgets import stat_card
from ..context import Ctx


def register(ctx: Ctx) -> None:
    @ui.page("/")
    def index():
        with frame(ctx, "dashboard"):
            actions = page_header("Dashboard", "AI-assisted pull-request reviews. Nothing is published until you confirm it.")
            with actions:
                btn("New review", "add", lambda: ui.navigate.to("/review/new"), kind="primary")

            cards = ui.row().classes("w-full gap-4 no-wrap overflow-x-auto")

            def draw_cards() -> None:
                s = ctx.services.db.stats()
                cards.clear()
                with cards:
                    stat_card("Reviews", s["total"], "fact_check")
                    stat_card("Completed", s["completed"], "task_alt")
                    stat_card("Findings", s["findings"], "bug_report")
                    stat_card("Tests generated", s["tests"], "science")
                    stat_card("Published", s["published"], "publish")

            draw_cards()
            ui.timer(5.0, draw_cards)

            if not ctx.services.db.list_reviews(1):
                getting_started(ctx)

            with card("Recent reviews"):
                if not ctx.services.db.list_reviews(1):
                    with empty_state("rate_review", "No reviews yet",
                                     "Pick an AI model in Settings, then paste a public pull-request link — or sign in to GitHub to choose from your repos."):
                        with ui.row().classes("gap-2 mt-3"):
                            btn("Open settings", "tune", lambda: ui.navigate.to("/settings"), kind="secondary")
                            btn("Start a review", "add", lambda: ui.navigate.to("/review/new"), kind="primary")
                else:
                    reviews_table(ctx, limit=25, pagination=8)


def getting_started(ctx: Ctx) -> None:
    """First-run checklist. Everything here is your own account/key; nothing is bundled with the app."""
    mgr = ctx.services.config_mgr
    has_key, has_gh = bool(mgr.get_openrouter_key()), bool(mgr.get_github_token())
    steps = [
        (has_key, "Pick an AI model", "Free and private: install Ollama (ollama.com), then Settings → AI models → Get more models. "
               "Or paste your own free OpenRouter key." + (" OpenRouter key saved." if has_key else "")),
        (has_gh, "Connect GitHub (optional)", "Public pull requests work without signing in. Sign in with a personal access "
                 "token or your own OAuth app to review private repos and publish comments."),
        (False, "Sandbox tests (optional)", "Install Docker Desktop to run generated tests in an isolated container."),
    ]
    with card("Get started"):
        for i, (done, title, text) in enumerate(steps, 1):
            with ui.row().classes("items-start no-wrap gap-3 w-full"):
                ui.icon("check_circle" if done else ("looks_one", "looks_two", "looks_3")[i - 1],
                        size="22px").classes("zp-ok" if done else "text-blue-300")
                with ui.column().classes("gap-0 min-w-0"):
                    ui.label(title).classes("zp-h3")
                    ui.label(text).classes("zp-sub")
