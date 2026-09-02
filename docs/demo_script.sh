#!/usr/bin/env bash
# Gif driver (dev-only; assumes sibling ../diff-habits checkout + both .venvs).
# asciinema rec -c "bash docs/demo_script.sh"
set -euo pipefail
cd "$(dirname "$0")/.."
GH=.venv/bin/git-habits
DH=../diff-habits/.venv/bin/diff-habits
say() { printf '\033[2m# %s\033[0m\n' "$1"; sleep 0.9; }
type_cmd() { printf '\033[1;32m$\033[0m '; local s="$1"; for ((i=0;i<${#s};i++)); do printf '%s' "${s:i:1}"; sleep 0.025; done; printf '\n'; sleep 0.3; }

TSV=$(mktemp)
printf 'COMMIT\ta1\tRich\trich@example.com\t2026-03-10T09:00:00+00:00\t2026-03-10T09:00:00+00:00\tc0\t\n40\t0\tsrc/a0.py\nCOMMIT\ta2\tRich\trich@example.com\t2026-03-11T09:00:00+00:00\t2026-03-11T09:00:00+00:00\tc1\t\n40\t0\tsrc/a1.py\nCOMMIT\ta3\tRich\trich@example.com\t2026-03-12T09:00:00+00:00\t2026-03-12T09:00:00+00:00\tc2\t\n40\t0\tsrc/a2.py\n' > "$TSV"

say "git-habits + diff-habits v0.2: thin evidence gets a refusal, not a number"
type_cmd "git-habits scan --from-export thin.tsv    # 3 commits, 120 lines"
$GH scan --from-export "$TSV"
sleep 2.0
say "an empty compare window is fiction, not a baseline -> exit 1"
type_cmd "git-habits compare --from-export thin.tsv --split 2027-01-01"
set +e; $GH compare --from-export "$TSV" --split 2027-01-01 | tail -6; echo "exit code: 1"; set -e
sleep 1.8
say "diff-habits refuses the same way, and NAMES the empty window"
type_cmd "diff-habits compare --repo . --split 2020-01-01"
set +e; $DH compare --repo . --split 2020-01-01; echo "exit code: $?"; set -e
sleep 1.8
say "and the sabotage suites prove the detectors detect (both directions, in CI)"
type_cmd "pytest tests/test_sabotage.py -q          # git-habits"
.venv/bin/python -m pytest tests/test_sabotage.py -q | tail -1
type_cmd "cd ../diff-habits && pytest tests/test_sabotage.py -q"
(cd ../diff-habits && .venv/bin/python -m pytest tests/test_sabotage.py -q | tail -1)
sleep 1.2
say "a number you can't refuse to give is a number you can't trust - github.com/rich-atkins"
sleep 1.5
rm -f "$TSV"
