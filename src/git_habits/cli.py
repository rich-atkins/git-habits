"""Command line interface.

Three commands:
    scan      metrics for one selection
    compare   two periods side by side, split on a date
    detect    find when habits changed, without being told the date
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime, timezone

from .exclude import DEFAULT_PATTERNS, Excluder, ExclusionReport
from .metrics import Metrics, compute
from .model import Commit
from .parse import LOG_ARGS, ParseError, from_export, from_repo


def _load(args) -> list[Commit]:
    if args.from_export:
        return from_export(args.from_export)
    return from_repo(args.repo, all_refs=args.all_refs)


def _select(commits: list[Commit], author: str | None, since: str | None, until: str | None) -> list[Commit]:
    out = commits
    if author:
        pat = re.compile(author, re.IGNORECASE)
        out = [c for c in out if pat.search(c.author_email) or pat.search(c.author_name)]
    if since:
        d = _date(since)
        out = [c for c in out if c.authored_at >= d]
    if until:
        d = _date(until)
        out = [c for c in out if c.authored_at <= d]
    return out


def _date(s: str) -> datetime:
    d = datetime.fromisoformat(s)
    return d if d.tzinfo else d.replace(tzinfo=timezone.utc)


def _excluder(args) -> Excluder:
    return Excluder(extra=args.exclude or [], disable=args.no_exclude or [])


def _fmt_exclusion(r: ExclusionReport) -> str:
    lines = [
        f"  ruleset v{r.ruleset_version}  "
        f"excluded {r.excluded_churn:,} of {r.total_churn:,} changed lines ({r.excluded_pct:.1f}%)"
    ]
    for cat, churn in sorted(r.by_category.items(), key=lambda kv: -kv[1]):
        lines.append(f"    {cat:<16} {churn:>10,}")
    if r.is_heavy:
        lines.append(
            "  NOTE: over half the churn was excluded. That is normal for repositories "
            "that commit lockfiles or build output, but read the kept figures knowing it."
        )
    return "\n".join(lines)


def _fmt_metrics(label: str, m: Metrics) -> str:
    d = m.as_dict()
    return "\n".join([
        f"  {label}",
        f"    window            {d['first_commit']} to {d['last_commit']}  "
        f"({d['span_days']}d span, {d['active_days']} active)",
        f"    commits           {d['commits']:,}   ({d['commits_per_active_day']}/active day)",
        f"    changed lines     {d['churn']:,}",
        f"    lines/commit      mean {d['lines_per_commit']}  p50 {d['lines_per_commit_p50']}  p90 {d['lines_per_commit_p90']}",
        f"    moved (reuse)     {d['moved_pct']}%  ({d['moved_per_kloc']} per 1k changed lines)",
        f"    legacy touch      {d['legacy_pct']}%  ({d['legacy_per_kloc']} per 1k)",
        f"    rework <=14d      {d['rework_pct']}%  ({d['rework_per_kloc']} per 1k)",
        f"    AI co-authored    " + (
            f"{d['ai_coauthored_commits']} commits ({d['ai_coauthored_pct']}%)"
            if d["trailers_captured"]
            else "not captured by this source (unknown, not zero)"
        ),
    ])


def _notes(*ms: Metrics) -> str:
    seen: list[str] = []
    for m in ms:
        for n in m.notes:
            if n not in seen:
                seen.append(n)
    return "\n".join(f"  ! {n}" for n in seen)


def cmd_scan(args) -> int:
    all_commits = _load(args)
    kept_all, _ = _excluder(args).apply(all_commits)
    sel = _select(kept_all, args.author, args.since, args.until)
    _, rep = _excluder(args).apply(_select(all_commits, args.author, args.since, args.until))
    m = compute(sel, history=kept_all)

    if args.json:
        print(json.dumps({"metrics": m.as_dict(), "excluded_pct": round(rep.excluded_pct, 2)}, indent=2))
        return 0
    print(f"\ngit-habits scan  (log args: {' '.join(LOG_ARGS)}"
          f"{' --all' if args.all_refs else ''})\n")
    print(_fmt_exclusion(rep))
    print()
    print(_fmt_metrics(args.label or "selection", m))
    n = _notes(m)
    if n:
        print("\n" + n)
    print()
    return 0


def cmd_compare(args) -> int:
    all_commits = _load(args)
    kept_all, rep = _excluder(args).apply(all_commits)
    scoped = _select(kept_all, args.author, args.since, args.until)
    split = _date(args.split)
    before = [c for c in scoped if c.authored_at < split]
    after = [c for c in scoped if c.authored_at >= split]

    mb = compute(before, history=kept_all)
    ma = compute(after, history=kept_all)

    if args.json:
        print(json.dumps({
            "split": args.split,
            "before": mb.as_dict(),
            "after": ma.as_dict(),
            "excluded_pct": round(rep.excluded_pct, 2),
        }, indent=2))
        return 0

    print(f"\ngit-habits compare  split at {args.split}\n")
    print(_fmt_exclusion(rep))
    print()
    print(_fmt_metrics(args.before_label, mb))
    print()
    print(_fmt_metrics(args.after_label, ma))
    print("\n  deltas (after vs before)")
    for key, label in [
        ("lines_per_commit", "lines/commit"),
        ("moved_pct", "moved %"),
        ("legacy_pct", "legacy %"),
        ("rework_pct", "rework %"),
        ("commits_per_active_day", "commits/active day"),
    ]:
        b, a = mb.as_dict()[key], ma.as_dict()[key]
        arrow = "->"
        pct = f"{((a - b) / b * 100):+.0f}%" if b else "n/a"
        print(f"    {label:<20} {b:>10} {arrow} {a:<10} {pct}")
    n = _notes(mb, ma)
    if n:
        print("\n" + n)
    print()
    return 0


def cmd_detect(args) -> int:
    """Find the largest month-on-month shift in commit size.

    Reported as a candidate with its effect size, never as a fact. People
    misremember when they changed how they work, which is the whole reason this
    exists, but a step in the data is evidence of something, not proof of what.
    """
    all_commits = _load(args)
    kept, _ = _excluder(args).apply(all_commits)
    sel = _select(kept, args.author, None, None)
    buckets: dict[str, list[int]] = {}
    for c in sel:
        buckets.setdefault(c.authored_at.strftime("%Y-%m"), []).append(c.churn)

    months = sorted(k for k, v in buckets.items() if len(v) >= args.min_commits)
    if len(months) < 4:
        print(f"not enough months with >= {args.min_commits} commits to detect a changepoint")
        return 1

    print(f"\ngit-habits detect  (months with >= {args.min_commits} commits)\n")
    print(f"  {'month':<10} {'commits':>8} {'churn':>10} {'lines/commit':>14}")
    series: list[tuple[str, float]] = []
    for mth in months:
        v = buckets[mth]
        lpc = sum(v) / len(v)
        series.append((mth, lpc))
        print(f"  {mth:<10} {len(v):>8} {sum(v):>10,} {lpc:>14.0f}")

    best, best_ratio = None, 1.0
    for i in range(1, len(series)):
        prev = sum(x for _, x in series[:i]) / i
        nxt = sum(x for _, x in series[i:]) / (len(series) - i)
        ratio = max(nxt / prev, prev / nxt) if prev and nxt else 1.0
        if ratio > best_ratio:
            best, best_ratio = series[i][0], ratio

    print()
    if best and best_ratio >= args.min_ratio:
        print(f"  candidate changepoint: {best}  (mean lines/commit shifts {best_ratio:.1f}x)")
        print("  This is a candidate, not a finding. Month buckets cannot locate a")
        print("  mid-month change: confirm against your own record, then pass --split.")
    else:
        print(f"  no changepoint above {args.min_ratio}x. Habits look stable, or the")
        print("  change is not visible in commit size.")
    print()
    return 0


def _common(p: argparse.ArgumentParser) -> None:
    src = p.add_mutually_exclusive_group(required=True)
    src.add_argument("--repo", help="path to a git repository")
    src.add_argument("--from-export", help="path to a git log export (TSV)")
    p.add_argument("--author", help="regex matched against author name and email")
    p.add_argument("--all-refs", action="store_true",
                   help="include all refs, not just HEAD. Can change commit counts by 2x or more")
    p.add_argument("--exclude", action="append", help="extra glob to exclude (repeatable)")
    p.add_argument("--no-exclude", action="append",
                   choices=sorted(DEFAULT_PATTERNS), help="disable a default category (repeatable)")
    p.add_argument("--json", action="store_true", help="emit JSON")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(
        prog="git-habits",
        description="Measure refactoring, duplication and churn from your own git history.",
    )
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("scan", help="metrics for one selection")
    _common(s)
    s.add_argument("--since")
    s.add_argument("--until")
    s.add_argument("--label")
    s.set_defaults(fn=cmd_scan)

    c = sub.add_parser("compare", help="two periods either side of a date")
    _common(c)
    c.add_argument("--split", required=True, help="ISO date, e.g. 2026-04-13")
    c.add_argument("--since")
    c.add_argument("--until")
    c.add_argument("--before-label", default="before")
    c.add_argument("--after-label", default="after")
    c.set_defaults(fn=cmd_compare)

    d = sub.add_parser("detect", help="find a candidate changepoint")
    _common(d)
    d.add_argument("--min-commits", type=int, default=5)
    d.add_argument("--min-ratio", type=float, default=1.5)
    d.set_defaults(fn=cmd_detect)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except ParseError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
