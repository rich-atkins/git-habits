"""Turn git history into `Commit` records — from a live repo or an export file.

Both paths converge on the same record shape so metrics never care which was used.
The export path exists because the repository you want to measure is often on a
machine you cannot clone from.

The canonical log invocation is defined once, here, in LOG_ARGS. Every number this
tool reports depends on those flags, so they are printed in the report header and
recorded in the JSON output rather than left implicit.
"""
from __future__ import annotations

import re
import subprocess
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from .model import Commit, FileChange

# --- the one true log invocation -------------------------------------------------
# %x09 is a literal tab. The format string MUST contain a % placeholder: git treats a
# placeholder-free string as a *named pretty alias* lookup, silently emits nothing and
# exits 0. That failure cost a day during this tool's own development.
# Field 8 captures Co-Authored-By trailers on a single line. Bodies (%b) are
# multi-line and would corrupt a line-oriented export, so trailers are extracted
# explicitly instead. Exports lacking field 8 parse fine and report AI attribution
# as unknown rather than zero.
COMMIT_FORMAT = (
    "COMMIT%x09%H%x09%an%x09%ae%x09%aI%x09%cI%x09%s"
    "%x09%(trailers:key=Co-Authored-By,valueonly,separator=%x2C)"
)

# The original 7-field format, still readable. Kept so earlier exports remain usable.
COMMIT_FORMAT_V1 = "COMMIT%x09%H%x09%an%x09%ae%x09%aI%x09%cI%x09%s"

LOG_ARGS = [
    "--no-merges",       # merge commits carry no authored change of their own
    "--numstat",         # per-file added/deleted counts, no diff content
    "-M",                # detect renames
    "-C",                # detect copies
    "--find-copies-harder",
]

_RENAME_BRACE = re.compile(r"^(.*?)\{(.*?) => (.*?)\}(.*)$")


class ParseError(RuntimeError):
    pass


def _parse_path(raw: str) -> tuple[str, str | None]:
    """Resolve git's rename notation to (new_path, old_path_or_None).

    git emits renames two ways:
        src/{old => new}/file.ts     -> brace form, common with shared prefixes
        old/path.ts => new/path.ts   -> plain form
    Left unresolved, a moved file is counted as two unrelated paths and every
    exclusion rule and per-path metric silently double-counts it.
    """
    m = _RENAME_BRACE.match(raw)
    if m:
        prefix, old_mid, new_mid, suffix = m.groups()
        old = f"{prefix}{old_mid}{suffix}".replace("//", "/")
        new = f"{prefix}{new_mid}{suffix}".replace("//", "/")
        return new, old
    if " => " in raw:
        old, new = raw.split(" => ", 1)
        return new.strip(), old.strip()
    return raw, None


def _parse_count(tok: str) -> int | None:
    """git writes '-' for binary files."""
    return None if tok == "-" else int(tok)


def parse_stream(lines: Iterable[str]) -> Iterator[Commit]:
    """Parse `git log` output (live or exported) into Commit records."""
    current: Commit | None = None
    for raw_line in lines:
        line = raw_line.rstrip("\n")
        if not line:
            continue
        if line.startswith("COMMIT\t"):
            if current is not None:
                yield current
            parts = line.split("\t")
            # COMMIT, sha, name, email, authored, committed, subject[, trailers]
            if len(parts) < 7:
                parts += [""] * (7 - len(parts))
            has_trailers = len(parts) >= 8
            current = Commit(
                sha=parts[1],
                author_name=parts[2],
                author_email=parts[3],
                authored_at=_parse_dt(parts[4]),
                committed_at=_parse_dt(parts[5]) if parts[5] else None,
                subject=parts[6],
                trailers="\t".join(parts[7:]) if has_trailers else None,
            )
            continue

        cols = line.split("\t")
        if len(cols) >= 3 and current is not None:
            added, deleted, path_raw = cols[0], cols[1], "\t".join(cols[2:])
            try:
                a, d = _parse_count(added), _parse_count(deleted)
            except ValueError:
                # Not a numstat row (e.g. a subject line that survived a bad format).
                continue
            path, old = _parse_path(path_raw)
            current.files.append(FileChange(path=path, added=a, deleted=d, renamed_from=old))

    if current is not None:
        yield current


def _parse_dt(token: str) -> datetime:
    token = token.strip()
    if not token:
        raise ParseError("missing date in COMMIT row")
    return datetime.fromisoformat(token)


def from_export(path: str | Path) -> list[Commit]:
    """Parse a TSV export produced by `git log` with COMMIT_FORMAT."""
    p = Path(path)
    text = p.read_text(encoding="utf-8", errors="replace")
    commits = list(parse_stream(text.splitlines()))
    if not commits:
        raise ParseError(
            f"{p} produced no commits. If it was generated with --format lacking a "
            f"'%' placeholder, git silently emitted nothing. Regenerate with "
            f"--format=\"{COMMIT_FORMAT}\"."
        )
    return commits


def from_repo(repo: str | Path, all_refs: bool = False, extra: list[str] | None = None) -> list[Commit]:
    """Run git log against a working repository.

    `all_refs=True` adds --all, which includes unmerged branch work. It can change
    commit counts by 2x or more, so it is an explicit, recorded choice rather than
    a default.
    """
    cmd = ["git", "-C", str(repo), "log"]
    if all_refs:
        cmd.append("--all")
    cmd += LOG_ARGS + [f"--format={COMMIT_FORMAT}"] + (extra or [])
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        raise ParseError(f"git log failed: {proc.stderr.strip()}")
    commits = list(parse_stream(proc.stdout.splitlines()))
    if not commits:
        raise ParseError(
            f"git log returned no commits for {repo}. Check the ref range and author "
            f"filters — an over-narrow --author matches nothing and exits 0."
        )
    return commits
