# git-habits

**What did your codebase's habits look like before, and after? Ask git.**

Measure refactoring, reuse and churn from your own git history, and compare any two
periods. For example, before and after your team adopted AI coding tools.

Runs entirely locally. It reads commit metadata and per-file line counts. It never
reads file contents, never uploads anything, and has no network access at all. That
is deliberate: the people who most want this answer usually cannot paste an employer's
codebase into a SaaS tool.

## Why

Industry research through 2026 reports that refactoring is falling while duplication
climbs. Whatever you make of those numbers, they describe a global average, and a
global average has never told anyone what is happening in *their* repository.

This tool computes comparable signals from history you already have, so you can check
the claim instead of inheriting it.

## Install

```bash
git clone https://github.com/rich-atkins/git-habits && cd git-habits
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
```

## Use

```bash
# one period
git-habits scan --repo . --author "you@example.com"

# before and after a date you changed how you work
git-habits compare --repo . --author "you@example.com" --split 2026-04-13

# no idea when that was? most people do not. find a candidate.
git-habits detect --repo . --author "you@example.com"
```

Working from a machine you cannot clone? Export the history there and analyse it here:

```bash
git log --all --no-merges --numstat -M -C --find-copies-harder --date=iso-strict \
  --format="COMMIT%x09%H%x09%an%x09%ae%x09%aI%x09%cI%x09%s%x09%(trailers:key=Co-Authored-By,valueonly,separator=%x2C)" \
  > repo-history.tsv

git-habits scan --from-export repo-history.tsv
```

## What you'll see

`compare` prints two `scan` blocks with a delta column. Run against a small seeded
demo (hand-coded, then AI-assisted, split at the changeover):

```text
git-habits compare --repo ./demo --author "dev@example.com" --split 2026-04-13

  before                                  after
    commits        4  (1.0/active day)      commits        4  (1.0/active day)
    changed lines  23                       changed lines  41
    lines/commit   p50 6.0                  lines/commit   p50 11.0
    moved (reuse)  0.0%                     moved (reuse)  12.2%
    rework <=14d   0.0%                     rework <=14d   24.39%
    AI co-authored 0 (0.0%)                 AI co-authored 4 (100.0%)

  deltas (after vs before)
    lines/commit   5.8 -> 10.2   +76%
    moved %        0.0 -> 12.2
    rework %       0.0 -> 24.39
```

Full `scan` and `compare` output, with the demo repo described, is in
[`docs/example-output.md`](docs/example-output.md). Read the *movement*, not the
absolute values — and mind the caveats below.

## What it measures

Everything comes from commit metadata and numstat counts, so it works identically on a
live repository or an export.

| Signal | Meaning |
|---|---|
| **moved %** | Share of changed lines in renamed or copied files. A reuse signal: it is what walking back through an earlier decision looks like in git. |
| **legacy touch %** | Share of changed lines landing on files untouched for a year or more. Whether old code is still being maintained. |
| **rework %** | Share of changed lines on files touched again within two weeks. Short-cycle churn. |
| **lines per commit** | Mean, median and p90. Median matters most; a handful of vendored dumps will wreck the mean. |
| **commits per active day** | Commit cadence, counting only days with commits. |
| **AI co-authored** | Commits carrying a `Co-Authored-By` AI trailer, when the source captured them. |

Every rate is reported as a percentage of changed lines **and** per thousand changed
lines. Per-line is primary because it stays stable when commit granularity changes,
which is exactly what happens when people change how they work.

## Exclusions are on by default, and reported

Unfiltered line counts are close to meaningless. One `npm install` writes tens of
thousands of lines to a lockfile. Measured on real repositories, generated artefacts
accounted for 48%, 61% and 62% of total churn.

So lockfiles, build output, vendored dependencies, minified bundles, generated code,
binaries and data dumps are excluded by default. Every run prints how much each
category removed, and warns when over half the churn is dropped. A tool that quietly
discards most of your data has an invisible thumb on the scale.

```bash
git-habits scan --repo . --exclude "docs/generated/**"   # add your own
git-habits scan --repo . --no-exclude data_dumps         # or keep a category
```

## Companion tool

[**diff-habits**](https://github.com/rich-atkins/diff-habits) measures what this one deliberately
cannot: it reads diff contents and counts **error-masking constructs**, the empty catch
blocks, silenced exceptions and suppressed type checks that remove the evidence of a
failure rather than handle it.

They are two tools rather than one with a flag, and the boundary is the point. `git-habits`
works from commit metadata and never opens a source file, so you can run it on an
employer's repository without a conversation. Reading source is a different decision, and
it should be a different install rather than a flag you might not notice. `diff-habits`
depends on this package, so exclusion rules are shared and the two tools' numbers stay
comparable.

## What this tool cannot tell you

Worth reading before quoting a number from it.

- **It cannot detect AI.** It detects *when things changed*. The before/after split is
  only as honest as you are about when you changed method.
- **A missing `Co-Authored-By` trailer does not mean a human wrote it.** Trailers get
  omitted on chores and quick fixes. Treat co-authorship as a lower bound, never as an
  AI-versus-human split.
- **Correlation, and not much of it.** What you were working on may have changed at the
  same time as how you worked. A greenfield quarter looks exactly like a refactoring
  collapse.
- **`moved %` measures file renames and copies**, which is a proxy for refactoring, not
  a measure of it. Line-level move detection needs diff contents, which this
  deliberately does not read.
- **A young repository cannot contain year-old code**, so the legacy rate climbs as a
  repo ages regardless of behaviour. The tool warns when a window opens on a repo too
  young to support the signal.
- **Small windows produce volatile rates.** Under thirty commits, it says so.
- **`--all-refs` can change commit counts twofold** by including unmerged branch work.
  It is off by default, and the flags used are printed with every result.

None of these are hidden in an FAQ because every one of them has already produced a
wrong number during this tool's own development.

## Licence

MIT, © Richard Atkins.
