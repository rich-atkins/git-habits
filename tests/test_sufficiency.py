"""Evidence-sufficiency guards (v0.2): unknown is not zero, and thin is not evidence.

Regression lineage: v0.1 once reported '0% AI co-authored' when trailers were never
captured (unknown rendered as zero). These tests pin the generalisation: ANY metric
whose denominator is below the evidence floor refuses to be a number, an empty
window refuses to be a report, and a compare against an empty window refuses to be
a comparison (exit 1), instead of printing a fully-formed block of fictional zeros
at exit 0 — which is exactly what v0.1 did.
"""
from __future__ import annotations

import io
import json
from contextlib import redirect_stdout

from test_core import _commit  # synthetic TSV helpers, same style as the unit tests

from git_habits.cli import main
from git_habits.metrics import compute
from git_habits.parse import parse_stream


def _export(tmp_path, rows: list[str]):
    p = tmp_path / "log.tsv"
    p.write_text("\n".join(rows) + "\n")
    return str(p)


def _thin_history() -> list[str]:
    # 3 commits, 120 changed lines: below both floors (5 commits, 200 lines).
    rows: list[str] = []
    for i in range(3):
        rows += _commit(f"aaa{i}", f"2026-03-{10 + i:02d}",
                        [("40", "0", f"src/a{i}.py")], sub=f"c{i}", tr="")
    return rows


def test_insufficiency_map_covers_both_denominators():
    m = compute(list(parse_stream(_thin_history())))
    insuff = m.insufficiency()
    assert insuff["lines_per_commit"].startswith("n=3 commits")
    assert insuff["moved_pct"].startswith("n=120 changed lines")
    # Sufficient floors yield an empty map, not None.
    assert m.insufficiency(min_commits=1, min_lines=1) == {}


def test_scan_renders_insufficient_not_numbers(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["scan", "--from-export", _export(tmp_path, _thin_history())])
    out = buf.getvalue()
    assert rc == 0  # thin is reportable, with refusals inline; empty is not
    assert "insufficient (n=3 commits, need >=5)" in out
    assert "insufficient (n=120 changed lines, need >=200)" in out
    # The raw counts stay visible so the reader can see why.
    assert "commits           3" in out


def test_scan_empty_selection_fails_closed(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["scan", "--from-export", _export(tmp_path, _thin_history()),
                   "--author", "nobody-matches-this"])
    out = buf.getvalue()
    assert rc == 1
    assert "no commits in this selection" in out
    # The v0.1 fiction must be gone: no zero-block, no misattributed unknown.
    assert "0.0/active day" not in out
    assert "not captured by this source" not in out


def test_compare_refuses_empty_window(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["compare", "--from-export", _export(tmp_path, _thin_history()),
                   "--split", "2027-01-01"])  # everything lands in 'before'
    out = buf.getvalue()
    assert rc == 1
    assert "comparison refused" in out
    assert "deltas (after vs before)" not in out  # no delta table on refusal


def test_compare_delta_lines_respect_insufficiency(tmp_path):
    # Two thin windows: deltas must be refused per-metric, not computed.
    hist = list(_thin_history())
    for i in range(3):
        hist += _commit(f"bbb{i}", f"2026-06-{10 + i:02d}",
                        [("40", "0", f"src/b{i}.py")], sub=f"d{i}", tr="")
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["compare", "--from-export", _export(tmp_path, hist),
                   "--split", "2026-05-01"])
    out = buf.getvalue()
    assert rc == 0
    assert "insufficient evidence in both windows" in out


def test_floors_are_overridable(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = main(["scan", "--from-export", _export(tmp_path, _thin_history()),
                   "--min-evidence-commits", "1", "--min-evidence-lines", "1"])
    out = buf.getvalue()
    assert rc == 0
    assert "insufficient" not in out


def test_json_carries_insufficiency(tmp_path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        main(["scan", "--from-export", _export(tmp_path, _thin_history()), "--json"])
    d = json.loads(buf.getvalue())
    assert "lines_per_commit" in d["insufficient"]
    # Numeric values stay numeric in JSON; refusal is a sibling map.
    assert isinstance(d["metrics"]["lines_per_commit"], float)
