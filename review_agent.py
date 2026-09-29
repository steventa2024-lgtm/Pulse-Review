#!/usr/bin/env python
"""ZeroPulse PR Review Agent — command-line interface (shares the pipeline with the dashboard)."""
from __future__ import annotations

import argparse
import sys

DESCRIPTION = """Review a GitHub pull request with an open-weight model.
By default the review is generated locally and NOTHING is published. Use --post to publish explicitly."""


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="review_agent.py", description=DESCRIPTION,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("pr_url", nargs="?", help="Pull-request URL, e.g. https://github.com/OWNER/REPO/pull/123")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", help="review locally, do not publish (default)")
    mode.add_argument("--post", action="store_true", help="publish the review to GitHub as a COMMENT review (explicit)")
    p.add_argument("--post-mode", choices=["overview", "inline"], default="overview",
                   help="with --post: single overview review, or inline comments on verified lines")
    p.add_argument("--model", help="model id (OpenRouter free model or Ollama model name)")
    p.add_argument("--provider", choices=["openrouter", "ollama"], help="inference provider (default: from settings)")
    p.add_argument("--generate-tests", action="store_true", help="also generate one proposed test file")
    p.add_argument("--depth", choices=["quick", "standard", "deep"], help="review depth")
    p.add_argument("--output", metavar="PATH", help="write the report (Markdown, or JSON with --json) to PATH")
    p.add_argument("--json", action="store_true", help="emit the structured review result as JSON")
    p.add_argument("--allow-private-hosted", action="store_true",
                   help="consent to sending a PRIVATE repo's code to a hosted provider (OpenRouter)")
    p.add_argument("--no-save", action="store_true", help="do not store the review in the local history database")
    return p


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.pr_url:
        parser.print_help()
        return 0

    from core.github_client import GitHubError, InvalidPRUrl, parse_pr_url
    from core.logging_setup import setup_logging
    from core.providers import ProviderError
    from core.publisher import PublishError, PublishOptions
    from core.report import render_report
    from core.review_pipeline import ConsentRequired, ReviewCancelled
    from core.reviewer import ReviewError
    from core.services import AppServices

    try:
        ref = parse_pr_url(args.pr_url)
    except InvalidPRUrl as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    setup_logging(console=False)
    svc = AppServices()

    def progress(ev) -> None:  # progress → stderr keeps --json output clean
        if ev.state in ("running", "failed"):
            print(f"[{ev.label}] {ev.detail}".rstrip(), file=sys.stderr)

    opts = svc.review_options(depth=args.depth, generate_tests=True if args.generate_tests else False,
                              private_hosted_consent=True if args.allow_private_hosted else None)
    try:
        pipe = svc.pipeline(opts, provider=args.provider, model=args.model, progress=progress, persist=not args.no_save)
        outcome = pipe.run(ref)
    except ConsentRequired as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 3
    except (GitHubError, ProviderError, ReviewError) as exc:
        print(f"error: {getattr(exc, 'message', exc)}", file=sys.stderr)
        return 1
    except ReviewCancelled:
        print("cancelled", file=sys.stderr)
        return 1

    result = outcome.result
    text = result.model_dump_json(indent=2) if args.json else render_report(result, outcome.pr)
    if args.output:
        from pathlib import Path
        Path(args.output).write_text(text, encoding="utf-8")
        print(f"report written to {args.output}", file=sys.stderr)
    if args.json or not args.output:
        print(text)

    if args.post:
        if not outcome.review_id:
            print("error: --post requires the review to be stored (remove --no-save).", file=sys.stderr)
            return 1
        try:
            pub = svc.publisher()
            plan = pub.prepare(outcome.review_id, PublishOptions(mode=args.post_mode, include_test=bool(result.test_file)))
            rec = pub.publish(outcome.review_id, plan, ref.slug)  # --post is the explicit confirmation
            print(f"published: {rec.url} ({rec.inline_comments} inline comment(s))", file=sys.stderr)
        except (PublishError, GitHubError) as exc:
            print(f"error: not published: {getattr(exc, 'message', exc)}", file=sys.stderr)
            return 1
    else:
        print("dry run: nothing was published.", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
