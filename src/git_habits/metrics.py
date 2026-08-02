"""Metrics computed from git history alone.

Everything here works from commit metadata and numstat counts, which means it runs
identically against a live repository or an export from a machine you cannot clone.
No file contents are read, so nothing sensitive leaves the machine.

Content-dependent signals (block duplication, error-masking constructs, cross-file
connectivity) need diff bodies and are deliberately not in this module. They belong
to a later version that requires repo access, and pretending otherwise would put
numbers in reports that the input cannot support.

Normalisation: every rate is reported per thousand changed lines AND per commit.
Per-line is primary because it stays stable when commit granularity or volume shifts,
which is exactly what happens when a team changes how it works. Per-commit is kept
because it answers a different question and because a metric that moved only because
commits got bigger is an artefact the reader deserves to see.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import timedelta
from statistics import median

from .model import Commit

LEGACY_DAYS = 365
CHURN_WINDOW_DAYS = 14


@dataclass
class Metrics:
    commits: int = 0
    churn: int = 0
    files_touched: int = 0
    active_days: int = 0
    span_days: int = 0

    # reuse signals
    moved_churn: int = 0
    legacy_churn: int = 0
    # risk signals
    rework_churn: int = 0

    ai_coauthored_commits: int = 0
    trailers_captured: bool = False
    """False when the source never recorded trailers. Distinct from 'none found'."""
    lines_per_commit_p50: float = 0.0
    lines_per_commit_p90: float = 0.0
    first_commit: str = ""
    last_commit: str = ""
    notes: list[str] = field(default_factory=list)

    # --- rates, per thousand changed lines -------------------------------------
    @property
    def moved_per_kloc(self) -> float:
        return _rate(self.moved_churn, self.churn)

    @property
    def legacy_per_kloc(self) -> float:
        return _rate(self.legacy_churn, self.churn)

    @property
    def rework_per_kloc(self) -> float:
        return _rate(self.rework_churn, self.churn)

    # --- shares, as percentages of churn ---------------------------------------
    @property
    def moved_pct(self) -> float:
        return _pct(self.moved_churn, self.churn)

    @property
    def legacy_pct(self) -> float:
        return _pct(self.legacy_churn, self.churn)

    @property
    def rework_pct(self) -> float:
        return _pct(self.rework_churn, self.churn)

    @property
    def lines_per_commit(self) -> float:
        return self.churn / self.commits if self.commits else 0.0

    @property
    def commits_per_active_day(self) -> float:
        return self.commits / self.active_days if self.active_days else 0.0

    @property
    def ai_coauthored_pct(self) -> float | None:
        """None when trailers were never captured — an unknown, not a zero."""
        if not self.trailers_captured:
            return None
        return _pct(self.ai_coauthored_commits, self.commits)

    def as_dict(self) -> dict:
        return {
            "commits": self.commits,
            "churn": self.churn,
            "files_touched": self.files_touched,
            "span_days": self.span_days,
            "active_days": self.active_days,
            "first_commit": self.first_commit,
            "last_commit": self.last_commit,
            "lines_per_commit": round(self.lines_per_commit, 1),
            "lines_per_commit_p50": round(self.lines_per_commit_p50, 1),
            "lines_per_commit_p90": round(self.lines_per_commit_p90, 1),
            "commits_per_active_day": round(self.commits_per_active_day, 2),
            "moved_pct": round(self.moved_pct, 2),
            "moved_per_kloc": round(self.moved_per_kloc, 1),
            "legacy_pct": round(self.legacy_pct, 2),
            "legacy_per_kloc": round(self.legacy_per_kloc, 1),
            "rework_pct": round(self.rework_pct, 2),
            "rework_per_kloc": round(self.rework_per_kloc, 1),
            "ai_coauthored_commits": self.ai_coauthored_commits if self.trailers_captured else None,
            "ai_coauthored_pct": round(self.ai_coauthored_pct, 1) if self.ai_coauthored_pct is not None else None,
            "trailers_captured": self.trailers_captured,
            "notes": self.notes,
        }


def _rate(part: int, whole: int) -> float:
    return 1000.0 * part / whole if whole else 0.0


def _pct(part: int, whole: int) -> float:
    return 100.0 * part / whole if whole else 0.0


def compute(commits: list[Commit], history: list[Commit] | None = None) -> Metrics:
    """Compute metrics for `commits`.

    `history` is the full, unfiltered-by-period commit list used to establish when
    each path was previously touched. Without it, legacy and rework signals would be
    measured relative to the start of the window rather than the life of the file,
    which systematically understates both at the start of any period.
    """
    m = Metrics()
    if not commits:
        m.notes.append("no commits in range")
        return m

    ordered = sorted(commits, key=lambda c: c.authored_at)
    basis = sorted(history or commits, key=lambda c: c.authored_at)

    # When each path was last touched, walking the full history in order.
    last_touch: dict[str, object] = {}
    touch_log: dict[str, list] = {}
    for c in basis:
        for f in c.files:
            touch_log.setdefault(f.path, []).append(c.authored_at)

    in_scope = {c.sha for c in commits}
    sizes: list[int] = []
    days: set = set()

    for c in basis:
        counted = c.sha in in_scope
        if counted:
            m.commits += 1
            sizes.append(c.churn)
            days.add(c.authored_at.date())
            if c.trailers_captured:
                m.trailers_captured = True
                if c.ai_coauthored:
                    m.ai_coauthored_commits += 1

        for f in c.files:
            prev = last_touch.get(f.path)
            if counted:
                m.churn += f.churn
                m.files_touched += 1
                if f.is_rename:
                    m.moved_churn += f.churn
                if prev is not None:
                    age = c.authored_at - prev  # type: ignore[operator]
                    if age >= timedelta(days=LEGACY_DAYS):
                        m.legacy_churn += f.churn
                    elif age <= timedelta(days=CHURN_WINDOW_DAYS):
                        m.rework_churn += f.churn
            last_touch[f.path] = c.authored_at

    m.active_days = len(days)
    m.first_commit = ordered[0].authored_at.date().isoformat()
    m.last_commit = ordered[-1].authored_at.date().isoformat()
    m.span_days = (ordered[-1].authored_at - ordered[0].authored_at).days + 1
    if sizes:
        m.lines_per_commit_p50 = float(median(sizes))
        m.lines_per_commit_p90 = float(_percentile(sizes, 90))

    _add_validity_notes(m, basis, ordered)
    return m


def _add_validity_notes(m: Metrics, basis: list[Commit], window: list[Commit]) -> None:
    """Say what the data cannot support, in the output rather than the docs."""
    if basis:
        span = (basis[-1].authored_at - basis[0].authored_at).days
        if span < LEGACY_DAYS:
            m.notes.append(
                f"repository history spans {span} days, under the {LEGACY_DAYS}-day "
                f"legacy threshold: legacy signal is not measurable here"
            )
        elif window:
            # A young repository cannot contain year-old code, so the legacy rate
            # climbs purely as it ages. Comparing legacy across two windows of a
            # maturing repo measures the calendar, not a change in behaviour.
            age_at_start = (window[0].authored_at - basis[0].authored_at).days
            if age_at_start < LEGACY_DAYS:
                m.notes.append(
                    f"repository was only {age_at_start} days old when this window "
                    f"opened: the legacy rate is suppressed by repo age here, so do "
                    f"not read a rise against a later window as a change in habits"
                )
    if m.commits and m.commits < 30:
        m.notes.append(f"only {m.commits} commits in range: rates are volatile, treat as indicative")
    if m.moved_churn == 0 and m.churn:
        m.notes.append("no renames detected: confirm the log used -M -C --find-copies-harder")


def _percentile(values: list[int], pct: float) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    k = (len(s) - 1) * pct / 100.0
    lo, hi = int(k), min(int(k) + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)
