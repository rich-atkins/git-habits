"""Shared fixture: build real, deterministic git repositories for CLI-level tests.

The unit tests feed synthetic TSV logs to the parser; these helpers exist for the
sabotage self-tests, which must exercise the WHOLE pipeline (git log -> parse ->
exclude -> metrics -> CLI rendering) against an actual repository, because that is
the path a user runs. Everything is pinned (dates, author, content) so runs are
reproducible; nothing here touches the network or the user's own git config.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

AUTHOR = "Dev Example <dev@example.com>"


def _git(repo: Path, *args: str, env_dates: str | None = None) -> None:
    env = {
        "GIT_AUTHOR_NAME": "Dev Example",
        "GIT_AUTHOR_EMAIL": "dev@example.com",
        "GIT_COMMITTER_NAME": "Dev Example",
        "GIT_COMMITTER_EMAIL": "dev@example.com",
        "HOME": str(repo),  # isolate from the user's global git config
        "GIT_CONFIG_NOSYSTEM": "1",
    }
    if env_dates:
        env["GIT_AUTHOR_DATE"] = env_dates
        env["GIT_COMMITTER_DATE"] = env_dates
    subprocess.run(["git", *args], cwd=repo, env=env, check=True,
                   capture_output=True, text=True)


def make_repo(root: Path, commits: list[dict]) -> Path:
    """Build a repo from a commit spec list.

    Each spec: {"date": "2026-01-05T10:00:00", "files": {path: [lines]},
                "message": str, "trailer": str | None, "append": bool}
    `append` (default False) appends to files instead of overwriting, so churn
    accumulates the way real editing does.
    """
    repo = root / "repo"
    repo.mkdir(parents=True, exist_ok=True)
    _git(repo, "init", "-q", "-b", "main")
    for spec in commits:
        for path, lines in spec["files"].items():
            f = repo / path
            f.parent.mkdir(parents=True, exist_ok=True)
            text = "\n".join(lines) + "\n"
            if spec.get("append") and f.exists():
                f.write_text(f.read_text() + text)
            else:
                f.write_text(text)
        _git(repo, "add", "-A")
        msg = spec["message"]
        if spec.get("trailer"):
            msg = f"{msg}\n\n{spec['trailer']}"
        _git(repo, "commit", "-q", "--no-gpg-sign", "-m", msg,
             env_dates=spec["date"] + " +0000")
    return repo


def code_lines(n: int, tag: str, start: int = 0) -> list[str]:
    """N distinct, meaningful-looking code lines (no dupes across tags)."""
    return [f"def fn_{tag}_{start + i}(): return process({start + i})  # {tag}"
            for i in range(n)]
