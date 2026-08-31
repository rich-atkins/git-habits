"""Sabotage self-test: prove the tool CATCHES what it claims to measure.

A measurement tool's demo shows what output looks like; nothing in v0.1 proved the
tool would actually flag a regime change, or stay quiet when there isn't one. Both
directions matter: a detector that always fires is as broken as one that never does.
(Lesson imported from an eval gate that once reported PASS on zero judgments.)

Two real repositories are built for each test run:
  * PLANTED — a clear regime change after 2026-04-13: commit size jumps ~6x,
    cadence rises, AI co-author trailers appear.
  * CONTROL — the same shape throughout, no shift.
`compare` must flag the planted shift and must NOT flag the control.
"""
from __future__ import annotations

import json

from conftest import code_lines, make_repo

from git_habits.cli import main

SPLIT = "2026-04-13"
TRAILER = "Co-Authored-By: Claude <noreply@anthropic.com>"


def _planted(tmp_path):
    commits = []
    # Before: 9 hand-sized commits, 30 lines each, 3 per month Jan-Mar
    # (>=4 qualifying months across the whole repo is what `detect` needs).
    for i in range(9):
        commits.append({
            "date": f"2026-{1 + i // 3:02d}-{5 + (i % 3) * 9:02d}T10:00:00",
            "files": {f"src/mod_{i % 3}.py": code_lines(30, f"before{i}", start=i * 100)},
            "message": f"feat: hand-written change {i}",
            "append": True,
        })
    # After: 8 large AI-assisted commits, 180 lines each, 4 per month Jun-Jul.
    for i in range(8):
        commits.append({
            "date": f"2026-{6 + i // 4:02d}-{3 + (i % 4) * 7:02d}T{9 + i % 3}:30:00",
            "files": {f"src/mod_{i % 3}.py": code_lines(180, f"after{i}", start=1000 + i * 300)},
            "message": f"feat: agent-built change {i}",
            "trailer": TRAILER,
            "append": True,
        })
    return make_repo(tmp_path, commits)


def _control(tmp_path):
    commits = []
    for i in range(16):
        month = 1 + i // 3  # Jan..Jun, same regime throughout
        commits.append({
            "date": f"2026-{month:02d}-{3 + (i % 3) * 9:02d}T10:00:00",
            # 50 lines/commit keeps BOTH windows above the 200-line evidence
            # floor however the split lands.
            "files": {f"src/mod_{i % 3}.py": code_lines(50, f"steady{i}", start=i * 100)},
            "message": f"feat: steady change {i}",
            "append": True,
        })
    return make_repo(tmp_path, commits)


def _compare_json(repo) -> dict:
    import io
    from contextlib import redirect_stdout
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["compare", "--repo", str(repo), "--split", SPLIT, "--json"])
    assert rc == 0, buf.getvalue()
    return json.loads(buf.getvalue())


def test_planted_shift_is_flagged(tmp_path):
    d = _compare_json(_planted(tmp_path))
    before, after = d["before"], d["after"]
    # Commit size regime change must be visible and large.
    assert after["lines_per_commit"] > before["lines_per_commit"] * 3
    # AI trailers appear only after the split.
    assert after["ai_coauthored_pct"] == 100.0
    assert (before["ai_coauthored_pct"] or 0.0) == 0.0
    # Neither window may hide behind insufficiency — the fixture must be big
    # enough that the numbers are owed.
    assert d["insufficient"]["before"] == {}
    assert d["insufficient"]["after"] == {}


def test_control_repo_stays_quiet(tmp_path):
    d = _compare_json(_control(tmp_path))
    before, after = d["before"], d["after"]
    b, a = before["lines_per_commit"], after["lines_per_commit"]
    # Same regime: the size delta must be small (well under the planted 3x bar).
    assert abs(a - b) / b < 0.25
    assert d["insufficient"]["before"] == {}
    assert d["insufficient"]["after"] == {}


def test_detect_finds_the_planted_month(tmp_path):
    """The changepoint detector must locate the planted shift month unaided."""
    import io
    from contextlib import redirect_stdout
    repo = _planted(tmp_path)
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["detect", "--repo", str(repo), "--min-commits", "3"])
    out = buf.getvalue()
    assert rc == 0
    assert "candidate changepoint: 2026-06" in out, out
