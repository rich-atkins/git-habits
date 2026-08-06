# Example output

So you can see what to expect before running it on your own history, here is
`git-habits` run against a small **seeded demo repository**: eight commits by one
author across two periods — four hand-coded (Jan–Mar 2026) and four AI-assisted
(May–Jul 2026, carrying `Co-Authored-By` trailers) — split at `2026-04-13`.

The numbers are tiny on purpose. It is a fixture for showing the *shape* of the
report, not a dataset to draw conclusions from — hence the small-sample warnings,
which are exactly what the tool prints on any window this short.

## `scan` — one period

```text
git-habits scan --repo ./demo --author "dev@example.com"

git-habits scan  (log args: --no-merges --numstat -M -C --find-copies-harder)

  ruleset v1.0  excluded 0 of 64 changed lines (0.0%)

  selection
    window            2026-01-15 to 2026-07-01  (168d span, 8 active)
    commits           8   (1.0/active day)
    changed lines     64
    lines/commit      mean 8.0  p50 7.0  p90 12.6
    moved (reuse)     7.81%  (78.1 per 1k changed lines)
    legacy touch      0.0%  (0.0 per 1k)
    rework <=14d      15.62%  (156.2 per 1k)
    AI co-authored    4 commits (50.0%)

  ! repository history spans 167 days, under the 365-day legacy threshold: legacy signal is not measurable here
  ! only 8 commits in range: rates are volatile, treat as indicative
```

## `compare` — before and after a split

This is the headline: two `scan` blocks side by side with a delta column. Here the
split is the point the (seeded) author switched from hand-coding to AI-assisted work.

```text
git-habits compare --repo ./demo --author "dev@example.com" --split 2026-04-13

git-habits compare  split at 2026-04-13

  before
    window            2026-01-15 to 2026-03-10  (55d span, 4 active)
    commits           4   (1.0/active day)
    changed lines     23
    lines/commit      mean 5.8  p50 6.0  p90 7.0
    moved (reuse)     0.0%  (0.0 per 1k changed lines)
    legacy touch      0.0%  (0.0 per 1k)
    rework <=14d      0.0%  (0.0 per 1k)
    AI co-authored    0 commits (0.0%)

  after
    window            2026-05-05 to 2026-07-01  (58d span, 4 active)
    commits           4   (1.0/active day)
    changed lines     41
    lines/commit      mean 10.2  p50 11.0  p90 13.4
    moved (reuse)     12.2%  (122.0 per 1k changed lines)
    legacy touch      0.0%  (0.0 per 1k)
    rework <=14d      24.39%  (243.9 per 1k)
    AI co-authored    4 commits (100.0%)

  deltas (after vs before)
    lines/commit                5.8 -> 10.2       +76%
    moved %                     0.0 -> 12.2       n/a
    legacy %                    0.0 -> 0.0        n/a
    rework %                    0.0 -> 24.39      n/a
    commits/active day          1.0 -> 1.0        +0%
```

Read the movement, not the absolute values: on this fixture, lines per commit and
short-cycle rework both rise after the split. On a real repository with hundreds of
commits per window those rates are stable enough to mean something — and every caveat
in the README's "What this tool cannot tell you" still applies.
