"""Core record types.

One shape for everything downstream, whichever source it came from: a live git
repository or a `git log --numstat` export produced on another machine. Metrics
never know which.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime


@dataclass
class FileChange:
    """One numstat row: added/deleted line counts against one path.

    `added`/`deleted` are None for binary files, which git reports as `-`.
    """

    path: str
    added: int | None
    deleted: int | None
    renamed_from: str | None = None

    @property
    def is_binary(self) -> bool:
        return self.added is None or self.deleted is None

    @property
    def churn(self) -> int:
        """Changed lines. Binary files contribute zero, never None."""
        if self.is_binary:
            return 0
        return (self.added or 0) + (self.deleted or 0)

    @property
    def is_rename(self) -> bool:
        return self.renamed_from is not None


@dataclass
class Commit:
    sha: str
    author_name: str
    author_email: str
    authored_at: datetime
    committed_at: datetime | None
    subject: str
    files: list[FileChange] = field(default_factory=list)
    trailers: str | None = None
    """Co-Authored-By trailer values, or None when the source did not capture them.

    None and "" mean different things and must not be conflated. None is "we do not
    know"; "" is "we looked and there were none". Reporting an unknown as 0% would
    manufacture a finding out of a missing field, which is exactly the failure this
    tool exists to catch.
    """

    @property
    def churn(self) -> int:
        return sum(f.churn for f in self.files)

    @property
    def trailers_captured(self) -> bool:
        return self.trailers is not None

    @property
    def ai_coauthored(self) -> bool | None:
        """True/False when trailers were captured, None when they were not.

        A *missing* trailer never proves a human wrote the code. Trailers get
        omitted on quick fixes and chores. Treat this as a lower bound on AI
        involvement, never as an AI-versus-human split.
        """
        if self.trailers is None:
            return None
        t = self.trailers.lower()
        return any(k in t for k in ("claude", "copilot", "gpt", "cursor", "codex"))
