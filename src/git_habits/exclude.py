"""Exclusion rules — and, just as importantly, a record of what they removed.

Unfiltered line counts are close to meaningless. A single `npm install` writes
10k-30k lines to a lockfile; a committed build directory or pipeline log can be
half a repository's churn. Measured on real repositories during this tool's
development, generated artefacts accounted for 51%, 62% and 61% of total churn.

So exclusions are ON by default. The corollary is that a tool which silently
discards most of the data has an invisible thumb on the scale, which is why every
run reports its exclusion impact and no result is emitted without it.
"""
from __future__ import annotations

import fnmatch
from dataclasses import dataclass, field

from .model import Commit

# Versioned so a report can state which ruleset produced it.
RULESET_VERSION = "1.0"

DEFAULT_PATTERNS: dict[str, list[str]] = {
    "lockfiles": [
        "**/package-lock.json", "**/yarn.lock", "**/pnpm-lock.yaml", "**/npm-shrinkwrap.json",
        "**/poetry.lock", "**/Pipfile.lock", "**/Gemfile.lock", "**/Cargo.lock",
        "**/composer.lock", "**/go.sum", "**/Podfile.lock", "**/*.lock",
    ],
    "build_output": [
        "dist/**", "**/dist/**", "build/**", "**/build/**", "out/**", "**/out/**",
        "**/.next/**", "**/.svelte-kit/**", "**/.nuxt/**", "target/**",
        "**/coverage/**", "**/__pycache__/**", "**/*.egg-info/**",
    ],
    "vendored": ["**/node_modules/**", "**/vendor/**", "**/third_party/**", "**/bower_components/**"],
    "minified": ["**/*.min.js", "**/*.min.css", "**/*.map", "**/*.bundle.*"],
    "generated_code": [
        "**/*.generated.*", "**/*_pb2.py", "**/*_pb2_grpc.py", "**/*.pb.go",
        "**/migrations/**", "**/__snapshots__/**", "**/*.snap",
    ],
    "binary_media": [
        "**/*.png", "**/*.jpg", "**/*.jpeg", "**/*.gif", "**/*.webp", "**/*.svg",
        "**/*.ico", "**/*.avif", "**/*.woff", "**/*.woff2", "**/*.ttf", "**/*.eot",
        "**/*.pdf", "**/*.zip", "**/*.gz", "**/*.mp4", "**/*.mp3",
    ],
    "data_dumps": ["**/*.csv", "**/*.parquet", "**/*.xlsx", "**/*.sqlite", "**/*.db"],
    "logs": ["**/*.log", "logs/**"],
}


@dataclass
class ExclusionReport:
    """What the ruleset removed. Printed with every result, never optional."""

    ruleset_version: str = RULESET_VERSION
    kept_churn: int = 0
    excluded_churn: int = 0
    kept_files: int = 0
    excluded_files: int = 0
    by_category: dict[str, int] = field(default_factory=dict)
    custom_patterns: list[str] = field(default_factory=list)
    disabled_categories: list[str] = field(default_factory=list)

    @property
    def total_churn(self) -> int:
        return self.kept_churn + self.excluded_churn

    @property
    def excluded_pct(self) -> float:
        return 100.0 * self.excluded_churn / self.total_churn if self.total_churn else 0.0

    @property
    def is_heavy(self) -> bool:
        """Over half the churn removed. Not wrong, but the reader must be told."""
        return self.excluded_pct >= 50.0


class Excluder:
    def __init__(
        self,
        categories: dict[str, list[str]] | None = None,
        extra: list[str] | None = None,
        disable: list[str] | None = None,
    ) -> None:
        cats = dict(categories or DEFAULT_PATTERNS)
        for name in disable or []:
            cats.pop(name, None)
        self.categories = cats
        self.extra = list(extra or [])
        self.disabled = list(disable or [])
        self._cache: dict[str, str | None] = {}

    def category_for(self, path: str) -> str | None:
        """Return the category excluding this path, or None to keep it."""
        if path in self._cache:
            return self._cache[path]
        result: str | None = None
        for pattern in self.extra:
            if _match(path, pattern):
                result = "custom"
                break
        if result is None:
            for name, patterns in self.categories.items():
                if any(_match(path, p) for p in patterns):
                    result = name
                    break
        self._cache[path] = result
        return result

    def apply(self, commits: list[Commit]) -> tuple[list[Commit], ExclusionReport]:
        """Filter file changes, returning kept commits and an impact report.

        Commits left with no files survive as empty records: they still happened,
        and dropping them would quietly inflate per-commit averages.
        """
        report = ExclusionReport(custom_patterns=self.extra, disabled_categories=self.disabled)
        out: list[Commit] = []
        for c in commits:
            kept: list = []
            for f in c.files:
                cat = self.category_for(f.path)
                if cat is None:
                    kept.append(f)
                    report.kept_churn += f.churn
                    report.kept_files += 1
                else:
                    report.excluded_churn += f.churn
                    report.excluded_files += 1
                    report.by_category[cat] = report.by_category.get(cat, 0) + f.churn
            # Rebuild with every field carried across. Omitting one here silently
            # degrades a downstream metric to its default, which reads as a finding
            # rather than a bug — `trailers` was lost this way once already.
            out.append(
                Commit(
                    sha=c.sha, author_name=c.author_name, author_email=c.author_email,
                    authored_at=c.authored_at, committed_at=c.committed_at,
                    subject=c.subject, files=kept, trailers=c.trailers,
                )
            )
        return out, report


def _match(path: str, pattern: str) -> bool:
    if fnmatch.fnmatch(path, pattern):
        return True
    # fnmatch has no notion of '**', so '**/x' must also match a bare 'x' at root.
    if pattern.startswith("**/") and fnmatch.fnmatch(path, pattern[3:]):
        return True
    return False
