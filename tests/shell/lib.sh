#!/usr/bin/env bash
# bailiwick — shared helpers for the shell contract tests (tests/shell/test_*.sh).
#
# Every suite runs fully sandboxed: its own HOME, GNUPGHOME, git remotes (file://), and a stub
# `gh` on PATH — no network, no secrets, no state outside $T_SANDBOX. Must stay bash-3.2-clean
# (macOS CI runs these under /bin/bash 3.2 to prove the portability claims for real).

T_PASS=0; T_FAIL=0
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/../.." && pwd)"

t_ok()   { T_PASS=$((T_PASS+1)); printf '  ok   %s\n' "$1"; }
t_fail() { T_FAIL=$((T_FAIL+1)); printf '  FAIL %s\n' "$1"; }

assert_eq() {  # <desc> <expected> <actual>
  if [ "$2" = "$3" ]; then t_ok "$1"; else t_fail "$1 (expected [$2], got [$3])"; fi
}
assert_exit() {  # <desc> <expected-rc> <actual-rc>
  assert_eq "$1" "$2" "$3"
}
assert_contains() {  # <desc> <needle> <haystack-file-or-string>
  local hay="$3"
  [ -f "$hay" ] && hay="$(cat "$3")"
  case "$hay" in *"$2"*) t_ok "$1";; *) t_fail "$1 (missing [$2])";; esac
}
assert_not_contains() {  # <desc> <needle> <haystack-file-or-string>
  local hay="$3"
  [ -f "$hay" ] && hay="$(cat "$3")"
  case "$hay" in *"$2"*) t_fail "$1 (found [$2])";; *) t_ok "$1";; esac
}
assert_file()    { if [ -f "$2" ]; then t_ok "$1"; else t_fail "$1 (missing file $2)"; fi; }
assert_no_file() { if [ -f "$2" ]; then t_fail "$1 (unexpected file $2)"; else t_ok "$1"; fi; }

t_sandbox() {  # sets T_SANDBOX, sandboxed HOME, stub gh on PATH; cleans up on exit
  T_SANDBOX="$(mktemp -d "${TMPDIR:-/tmp}/bw-test.XXXXXX")"
  # Physical, normalized path: macOS TMPDIR ends in '/' and sits behind the /var -> /private/var
  # symlink, so string comparisons against paths the tools normalize would spuriously fail.
  T_SANDBOX="$(cd "$T_SANDBOX" && pwd -P)"
  export HOME="$T_SANDBOX/home"
  mkdir -p "$HOME"
  export XDG_CACHE_HOME="$T_SANDBOX/cache"
  export BAILIWICK_HOME="$T_SANDBOX/home/.bailiwick"
  export GH_STUB_LOG="$T_SANDBOX/gh-stub.log"
  export PATH="$REPO_ROOT/tests/shell/stub-bin:$PATH"
  # Isolate from any real git identity/config on the runner.
  export GIT_CONFIG_GLOBAL="$T_SANDBOX/gitconfig"
  git config --file "$GIT_CONFIG_GLOBAL" user.name bw-test
  git config --file "$GIT_CONFIG_GLOBAL" user.email test@local
  git config --file "$GIT_CONFIG_GLOBAL" init.defaultBranch main
  trap 'rm -rf "$T_SANDBOX"' EXIT
}

t_gen_gpg_key() {  # <gnupghome> <name> -> prints fingerprint; passphrase-less, with [E] subkey
  mkdir -p "$1" && chmod 700 "$1"
  GNUPGHOME="$1" gpg --batch --quiet --passphrase '' --quick-generate-key "$2" default default never 2>/dev/null
  GNUPGHOME="$1" gpg --list-keys --with-colons 2>/dev/null | awk -F: '/^fpr/{print $10; exit}'
}

t_make_instance() {  # <dir>: a committed framework instance repo with a file:// bare origin
  local inst="$1"
  mkdir -p "$inst/hooks" "$inst/scripts"
  cp "$REPO_ROOT"/hooks/*.sh "$REPO_ROOT"/hooks/*.py "$inst/hooks/" 2>/dev/null || true
  cp "$REPO_ROOT"/hooks/settings.template.json "$inst/hooks/"
  cp "$REPO_ROOT"/scripts/doctor.sh "$inst/scripts/"
  git -C "$inst" init -q -b main
  git -C "$inst" add -A
  git -C "$inst" -c user.name=bw-test -c user.email=test@local commit -qm "seed"
  git init -q --bare "$inst.origin.git"
  git -C "$inst" remote add origin "file://$inst.origin.git"
  git -C "$inst" push -q origin main
}

t_summary() {
  echo
  echo "$(basename "$0"): $T_PASS passed, $T_FAIL failed"
  [ "$T_FAIL" -eq 0 ]
}
