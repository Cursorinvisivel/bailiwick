#!/usr/bin/env bash
# Run every shell contract suite (tests/shell/test_*.sh). Each suite is independent and fully
# sandboxed; a suite's non-zero exit marks the run failed but the remaining suites still run.
# Invoked with the bash under test ($BASH propagates — on macOS CI that is /bin/bash 3.2).
set -u
HERE="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")" && pwd)"
SH="${BASH:-bash}"
failed=0
for t in "$HERE"/test_*.sh; do
  echo "==== $(basename "$t") ($("$SH" --version | head -1))"
  "$SH" "$t" || failed=1
  echo
done
if [ "$failed" -ne 0 ]; then
  echo "shell contract tests: FAILED"
  exit 1
fi
echo "shell contract tests: all suites passed"
