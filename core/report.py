"""Combined review report (Markdown) for download/CLI output."""
from __future__ import annotations

from .publisher import _fence, render_issue_md
from .schemas import PRData, ReviewResult


def render_report(result: ReviewResult, pr: PRData | None = None, review_url: str | None = None) -> str:
    m = result.metadata
    out = ["# PulseReview Report", ""]
    if pr:
        out += [f"**{pr.ref.full_name}#{pr.ref.number}** — {pr.title}  ", f"{pr.html_url or pr.ref.url}", ""]
    out += [f"- Overall risk: **{result.overall_risk}**",
            f"- Provider / model: `{m.provider}` / `{m.model}`",
            f"- Reviewed commit: `{m.head_sha or 'unknown'}`",
            f"- Depth: {m.depth}; model calls: {m.chunks}",
            "- Tokens: " + (f"{m.input_tokens} in / {m.output_tokens} out" if m.input_tokens is not None else "not reported by provider"),
            f"- Generated: {m.created_at}", "", "## Summary", "", result.summary or "_none_", "", "## Findings", ""]
    if not result.issues:
        out.append("_No defensible issues were found in the reviewed changes._")
    for n, i in enumerate(result.issues, 1):
        out += [f"### {n}. [{i.severity}] {i.title}", "", render_issue_md(i, heading=False), "",
                f"`{i.file}`" + (f":{i.line}" if i.line else "") + f" · {i.category} · {i.verification_status} · {i.source}", ""]
    out += ["## Files", "", "| File | Status | Note |", "|---|---|---|"]
    out += [f"| `{c.path}` | {c.status} | {c.reason} |" for c in result.files_reviewed]
    if result.test_file:
        t = result.test_file
        out += ["", "## Proposed test", "", f"`{t.filename}` — {t.framework} ({t.language}); artifact state: **{t.artifact_state}**; "
                f"execution: **{t.execution_status}**", "", t.purpose, ""]
        if t.needs_verification:
            out += ["> Requires verification: " + "; ".join(t.verification_notes), ""]
        out += [_fence(t.content, t.language)]
        if t.execution_output:
            out += ["", "Sandbox output:", _fence(t.execution_output[-4000:])]
    if result.limitations:
        out += ["", "## Limitations", ""] + [f"- {l}" for l in result.limitations]
    return "\n".join(out) + "\n"
