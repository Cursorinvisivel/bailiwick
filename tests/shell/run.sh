#!/usr/bin/env bash
# Run every shell contract suite (tests/shell/test_*.sh). Each suite is independent and fully
# sandboxed, so they run CONCURRENTLY — on the macOS runner (slow process spawn, the point of
# that leg) this roughly halves the wall clock. Output is buffered per suite and printed in
# order on completion, so the log reads exactly like the old serial run.
# Invoked with the bash under test ($BASH propagates — on macOS CI that is /bin/bash 3.2).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SH="${BASH:-bash}"
BUF="$(mktemp -d "${TMPDIR:-/tmp}/bw-run.XXXXXX")"
trap 'rm -rf "$BUF"' EXIT

suites=()
pids=()
i=0
for t in "$HERE"/test_*.sh; do
  suites[$i]="$t"
  "$SH" "$t" > "$BUF/$i.out" 2>&1 &
  pids[$i]=$!
  i=$((i+1))
done

failed=0
j=0
while [ "$j" -lt "$i" ]; do
  wait "${pids[$j]}" || failed=1
  echo "==== $(basename "${suites[$j]}") ($("$SH" --version | head -1))"
  cat "$BUF/$j.out"
  echo
  j=$((j+1))
done

if [ "$failed" -ne 0 ]; then
  echo "shell contract tests: FAILED"
  exit 1
fi
echo "shell contract tests: all suites passed"
