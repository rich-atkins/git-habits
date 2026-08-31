"""Tests for the parts that have already gone wrong once.

Every case below corresponds to a real bug found while building this tool against
live repositories. They are regression tests first and documentation second.
"""
from __future__ import annotations

import pytest

from git_habits.exclude import Excluder
from git_habits.metrics import compute
from git_habits.parse import ParseError, _parse_path, from_export, parse_stream

V2 = "COMMIT\t{sha}\tRich\trich@example.com\t{d}T09:00:00+00:00\t{d}T09:00:00+00:00\t{sub}\t{tr}"
V1 = "COMMIT\t{sha}\tRich\trich@example.com\t{d}T09:00:00+00:00\t{d}T09:00:00+00:00\t{sub}"


def _commit(sha, d, files, sub="work", tr=None, v1=False):
    head = (V1 if v1 else V2).format(sha=sha, d=d, sub=sub, tr=tr or "")
    return [head] + [f"{a}\t{dl}\t{p}" for a, dl, p in files]


# --- rename notation -------------------------------------------------------------

def test_brace_rename_resolves_to_new_and_old():
    new, old = _parse_path("src/{old => new}/file.ts")
    assert new == "src/new/file.ts"
    assert old == "src/old/file.ts"


def test_plain_rename_resolves():
    new, old = _parse_path("a/old.ts => b/new.ts")
    assert (new, old) == ("b/new.ts", "a/old.ts")


def test_non_rename_path_has_no_old():
    assert _parse_path("src/app.ts") == ("src/app.ts", None)


# --- binary files ----------------------------------------------------------------

def test_binary_contributes_zero_churn_not_none():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("-", "-", "logo.png")])))
    assert commits[0].files[0].is_binary
    assert commits[0].churn == 0


# --- trailers: unknown must never render as zero ---------------------------------

def test_v1_export_reports_trailers_as_unknown():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("5", "1", "a.ts")], v1=True)))
    assert commits[0].trailers is None
    assert commits[0].ai_coauthored is None
    assert compute(commits).as_dict()["ai_coauthored_pct"] is None


def test_v2_export_with_empty_trailers_is_captured_but_zero():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("5", "1", "a.ts")], tr="")))
    assert commits[0].trailers == ""
    assert commits[0].ai_coauthored is False
    assert compute(commits).as_dict()["ai_coauthored_pct"] == 0.0


def test_ai_trailer_detected():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("5", "1", "a.ts")], tr="Claude <noreply@anthropic.com>")))
    assert commits[0].ai_coauthored is True


def test_exclusion_preserves_trailers():
    """Regression: Excluder rebuilt Commit objects and dropped `trailers`,
    turning a known value into an unknown that then rendered as 0%."""
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("5", "1", "a.ts")], tr="Claude")))
    kept, _ = Excluder().apply(commits)
    assert kept[0].trailers == "Claude"
    assert kept[0].ai_coauthored is True


# --- exclusions ------------------------------------------------------------------

def test_lockfile_excluded_and_reported():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [
        ("10", "0", "src/a.ts"), ("9000", "0", "package-lock.json")])))
    kept, rep = Excluder().apply(commits)
    assert kept[0].churn == 10
    assert rep.excluded_churn == 9000
    assert rep.by_category["lockfiles"] == 9000
    assert rep.is_heavy


def test_commit_survives_when_all_files_excluded():
    """Dropping emptied commits would inflate per-commit averages."""
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("9000", "0", "yarn.lock")])))
    kept, _ = Excluder().apply(commits)
    assert len(kept) == 1 and kept[0].churn == 0


def test_disabling_a_category_keeps_those_paths():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("9000", "0", "package-lock.json")])))
    kept, rep = Excluder(disable=["lockfiles"]).apply(commits)
    assert kept[0].churn == 9000 and rep.excluded_churn == 0


# --- metrics ---------------------------------------------------------------------

def test_moved_churn_counted_from_renames():
    commits = list(parse_stream(_commit("a1", "2026-01-01", [("4", "4", "src/{a => b}/x.ts")])))
    m = compute(commits)
    assert m.moved_churn == 8 and m.moved_pct == 100.0


def test_rework_window_counts_second_touch():
    stream = _commit("a1", "2026-01-01", [("10", "0", "a.ts")]) + \
             _commit("a2", "2026-01-05", [("6", "2", "a.ts")])
    m = compute(list(parse_stream(stream)))
    assert m.rework_churn == 8  # only the second touch is rework


def test_legacy_not_counted_inside_a_year():
    stream = _commit("a1", "2026-01-01", [("10", "0", "a.ts")]) + \
             _commit("a2", "2026-06-01", [("4", "0", "a.ts")])
    assert compute(list(parse_stream(stream))).legacy_churn == 0


def test_legacy_counted_after_a_year():
    stream = _commit("a1", "2025-01-01", [("10", "0", "a.ts")]) + \
             _commit("a2", "2026-06-01", [("4", "0", "a.ts")])
    assert compute(list(parse_stream(stream))).legacy_churn == 4


def test_short_history_flags_legacy_as_unmeasurable():
    m = compute(list(parse_stream(_commit("a1", "2026-01-01", [("5", "0", "a.ts")]))))
    assert any("legacy signal is not measurable" in n for n in m.notes)


def test_history_argument_dates_files_from_before_the_window():
    """Without full history, a file's first touch inside the window looks new."""
    full = list(parse_stream(
        _commit("a1", "2025-01-01", [("10", "0", "a.ts")]) +
        _commit("a2", "2026-06-01", [("4", "0", "a.ts")])
    ))
    window = [c for c in full if c.sha == "a2"]
    assert compute(window, history=full).legacy_churn == 4
    assert compute(window).legacy_churn == 0


def test_empty_selection_is_safe():
    m = compute([])
    assert m.commits == 0 and "no commits in range" in m.notes


# --- the silent-zero failure that started all this -------------------------------

def test_empty_export_raises_rather_than_reporting_nothing():
    """`git log --format="COMMIT"` (no % placeholder) emits nothing and exits 0."""
    with pytest.raises(ParseError, match="no commits"):
        from_export("/dev/null")


# --- git %aI dates on Python 3.10 -------------------------------------------------

def test_utc_z_suffix_dates_parse():
    """git's %aI emits `2026-01-01T09:00:00Z` for UTC commits; fromisoformat
    rejects the Z until Python 3.11. Found by CI's 3.10 job the first time the
    sabotage suite ran against a real repository — v0.1 never parsed live-git
    dates in tests, so the floor claimed 3.10 without ever proving it."""
    row = "COMMIT\ta1\tRich\trich@example.com\t2026-01-01T09:00:00Z\t2026-01-01T09:00:00Z\twork\t"
    commits = list(parse_stream([row, "5\t1\ta.ts"]))
    assert commits[0].authored_at.isoformat() == "2026-01-01T09:00:00+00:00"
