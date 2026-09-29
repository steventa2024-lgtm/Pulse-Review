"""Unified-diff parsing with exact old/new line numbers and GitHub inline-comment location mapping."""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Literal

from .schemas import FileChange

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@(.*)$")


@dataclass
class DiffLine:
    kind: Literal["add", "del", "ctx"]
    text: str
    old_no: int | None
    new_no: int | None


@dataclass
class Hunk:
    old_start: int
    old_len: int
    new_start: int
    new_len: int
    header: str
    lines: list[DiffLine] = field(default_factory=list)

    @property
    def added(self) -> list[DiffLine]:
        return [l for l in self.lines if l.kind == "add"]

    @property
    def removed(self) -> list[DiffLine]:
        return [l for l in self.lines if l.kind == "del"]

    def render(self, numbered: bool = True) -> str:
        """Render for LLM/UI use. Lines show the real source line numbers (new for +/context, old for -)."""
        out = [f"@@ -{self.old_start},{self.old_len} +{self.new_start},{self.new_len} @@{self.header}"]
        for l in self.lines:
            sign = {"add": "+", "del": "-", "ctx": " "}[l.kind]
            if numbered:
                no = l.new_no if l.kind != "del" else l.old_no
                tag = f"R{no}" if l.kind != "del" else f"L{no}"
                out.append(f"{tag:>7} {sign}{l.text}")
            else:
                out.append(f"{sign}{l.text}")
        return "\n".join(out)


def parse_patch(patch: str | None) -> list[Hunk]:
    """Parse the ``patch`` string GitHub returns per file (hunks only, no file headers)."""
    hunks: list[Hunk] = []
    if not patch:
        return hunks
    cur: Hunk | None = None
    old_no = new_no = 0
    for raw in patch.splitlines():
        m = _HUNK.match(raw)
        if m:
            cur = Hunk(int(m.group(1)), int(m.group(2) or 1), int(m.group(3)), int(m.group(4) or 1), m.group(5))
            hunks.append(cur)
            old_no, new_no = cur.old_start, cur.new_start
            continue
        if cur is None:
            continue  # ignore any preamble (---/+++ headers, "diff --git")
        if raw.startswith("\\"):  # "\ No newline at end of file"
            continue
        if raw.startswith("+"):
            cur.lines.append(DiffLine("add", raw[1:], None, new_no))
            new_no += 1
        elif raw.startswith("-"):
            cur.lines.append(DiffLine("del", raw[1:], old_no, None))
            old_no += 1
        else:
            text = raw[1:] if raw.startswith(" ") else raw
            cur.lines.append(DiffLine("ctx", text, old_no, new_no))
            old_no += 1
            new_no += 1
    return hunks


def parse_unified_diff(text: str) -> dict[str, list[Hunk]]:
    """Parse a multi-file unified diff (``git diff`` output) into {path: hunks}."""
    files: dict[str, list[str]] = {}
    current: str | None = None
    for line in text.splitlines():
        if line.startswith("diff --git "):
            current = None
        elif line.startswith("+++ "):
            p = line[4:].strip()
            if p == "/dev/null":
                continue
            current = p[2:] if p.startswith(("b/", "a/")) else p
            files.setdefault(current, [])
        elif line.startswith("--- ") and current is None:
            p = line[4:].strip()
            if p != "/dev/null":
                current = p[2:] if p.startswith("a/") else p
                files.setdefault(current, [])
        elif current is not None:
            files[current].append(line)
    return {p: parse_patch("\n".join(ls)) for p, ls in files.items()}


class FileDiff:
    """Lookup structure for one changed file."""

    def __init__(self, path: str, hunks: list[Hunk]) -> None:
        self.path = path
        self.hunks = hunks
        self._right: dict[int, DiffLine] = {}
        self._left: dict[int, DiffLine] = {}
        for h in hunks:
            for l in h.lines:
                if l.new_no is not None:
                    self._right[l.new_no] = l
                if l.old_no is not None and l.kind == "del":
                    self._left[l.old_no] = l
        self._text = "\n".join(l.text for h in hunks for l in h.lines)
        self._norm = _norm(self._text)
        self._norm_redacted: str | None = None

    def is_valid_location(self, line: int | None, side: str = "RIGHT") -> bool:
        """True only if GitHub can anchor an inline comment there (a line visible in the diff)."""
        if line is None:
            return False
        return line in (self._right if side == "RIGHT" else self._left)

    def line_at(self, line: int, side: str = "RIGHT") -> DiffLine | None:
        return (self._right if side == "RIGHT" else self._left).get(line)

    def is_changed_line(self, line: int | None, side: str = "RIGHT") -> bool:
        l = self.line_at(line, side) if line else None
        return bool(l and l.kind in ("add", "del"))

    def contains(self, snippet: str) -> bool:
        s = _norm(snippet)
        if not s:
            return False
        if s in self._norm:
            return True
        if self._norm_redacted is None:  # the model only ever saw redacted text when secrets were present
            from .security import redact_secrets
            self._norm_redacted = _norm(redact_secrets(self._text)[0])
        return s in self._norm_redacted

    def nearest_changed_line(self, snippet: str) -> int | None:
        """Locate a quoted evidence line among added lines (helps when the model gives a wrong number)."""
        s = _norm(snippet.splitlines()[0]) if snippet.strip() else ""
        if not s:
            return None
        for h in self.hunks:
            for l in h.lines:
                if l.kind == "add" and s in _norm(l.text):
                    return l.new_no
        return None


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", s or "").strip().lower()


class DiffIndex:
    """Diff lookup for every reviewable file of a PR."""

    def __init__(self, files: list[FileChange]) -> None:
        self.files: dict[str, FileDiff] = {}
        for f in files:
            if f.patch:
                self.files[f.filename] = FileDiff(f.filename, parse_patch(f.patch))

    def get(self, path: str) -> FileDiff | None:
        return self.files.get(path)

    def has(self, path: str) -> bool:
        return path in self.files


def render_file_diff(path: str, hunks: list[Hunk], status: str = "modified") -> str:
    body = "\n".join(h.render() for h in hunks)
    return f"### FILE: {path} ({status})\n{body}"
