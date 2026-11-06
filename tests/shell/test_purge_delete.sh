#!/usr/bin/env bash
# Contract tests for scripts/purge_delete.sh — the /purge delete step.
#
# Pinned: it deletes only approved, hash-matching lists, only inside the allowed roots, never through
# a glob pathspec, a dot/empty component, or a symlink, and a surfaced knowledge file only when its
# frontmatter scope names the client. Every refused line is reported and changes nothing. Captures are
# deletable only directly inside the enumerated curate gather/retire dirs. A failed deletion is FAILED,
# exit 3, and names no path. The approval hash binds the list AND the from-file.
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

INST="$T_SANDBOX/inst"
mkdir -p "$INST/scripts"
cp "$REPO_ROOT/scripts/purge_delete.sh" "$INST/scripts/"
B="$(cd "$INST" && pwd -P)"
H="$BAILIWICK_HOME"; mkdir -p "$H/purge-work" "$H/captures/k1/raw"
W="$H/purge-work"
printf 'wmb\n' > "$W/from"
OUT="$T_SANDBOX/outside"; mkdir -p "$OUT/raw"

git -C "$B" init -q
mkdir -p "$B/knowledge/clients/wmb/sub" "$B/knowledge/clients/other" "$B/knowledge/topics" "$B/definitions/clients/wmb"
echo a > "$B/knowledge/clients/wmb/sub/a.md"
echo b > "$B/knowledge/clients/other/b.md"
echo idx > "$B/knowledge/INDEX.md"
printf -- '---\nscope: client:wmb\n---\nbody\n' > "$B/knowledge/topics/scoped.md"
printf -- '---\nscope: generic\n---\nmentions client:wmb in the body\n' > "$B/knowledge/topics/generic.md"
printf -- '---\nscope: client:wmb\n---\nx\n' > "$B/knowledge/topics/x\\y.md"   # a literal backslash
printf -- '---\nscope: generic\n---\nxy\n' > "$B/knowledge/topics/xy.md"
echo d > "$B/definitions/clients/wmb/spec.drawio"
git -C "$B" add -A && git -C "$B" commit -qm init

pd() { bash "$B/scripts/purge_delete.sh" "$@"; }
h256() { if command -v sha256sum >/dev/null 2>&1; then sha256sum | cut -d' ' -f1; else shasum -a 256 | cut -d' ' -f1; fi; }
sha() {  # <list> [from-file]: the approval hash, sha256("<sha256(list)>\n<sha256(from)>\n")
  printf '%s\n%s\n' "$(h256 < "$1")" "$(h256 < "${2:-$W/from}")" | h256
}
staged() { git -C "$B" diff --cached --name-only | wc -l | tr -d ' '; }
run_list() {  # <lines...>: write the list, apply with its own hash
  printf '%s\n' "$@" > "$W/targets"
  pd --list "$W/targets" --from-file "$W/from" --sha "$(sha "$W/targets")" --apply
}

echo "== refused lines print skip and stage/delete nothing"
out="$(run_list \
  "$B/knowledge/*.md" \
  "$B/knowledge//clients/other/b.md" \
  "$B/knowledge/./clients/other/b.md" \
  "$B/knowledge/clients/wmb/../other/b.md" \
  "$B/knowledge/clients/other/b.md" \
  "$B/knowledge/topics/generic.md" \
  "" \
  "relative/knowledge/topics/scoped.md" \
  "$B/knowledge/clients")"
assert_eq "nothing staged" "0" "$(staged)"
assert_contains "glob line refused" "line 1: skip (glob character)" "$out"
assert_contains "// refused" "line 2: skip (dot or empty path component)" "$out"
assert_contains "/./ refused" "line 3: skip (dot or empty path component)" "$out"
assert_contains ".. refused" "line 4: skip (dot or empty path component)" "$out"
assert_contains "other client refused" "line 5: skip (outside allowed roots)" "$out"
assert_contains "scope mismatch refused" "line 6: skip (scope is not client:<from>)" "$out"
assert_contains "empty line refused" "line 7: skip (empty line)" "$out"
assert_contains "relative refused" "line 8: skip (relative path)" "$out"
assert_contains "clients root refused" "line 9: skip (outside allowed roots)" "$out"
assert_file "INDEX.md intact" "$B/knowledge/INDEX.md"
assert_file "other client intact" "$B/knowledge/clients/other/b.md"
assert_file "generic topic intact" "$B/knowledge/topics/generic.md"
assert_not_contains "no path echoed" "$B" "$out"

echo "== symlinks: trailing slash on a symlinked dir, and a symlinked parent, are refused"
mkdir -p "$OUT/tree"; echo keep > "$OUT/tree/keep.md"; echo keep > "$OUT/raw/s.jsonl"
ln -s "$OUT/tree" "$B/knowledge/clients/wmb-link"
printf 'wmb-link\n' > "$W/from-link"
printf '%s\n' "$B/knowledge/clients/wmb-link/" > "$W/targets"
out="$(pd --list "$W/targets" --from-file "$W/from-link" --sha "$(sha "$W/targets" "$W/from-link")" --apply)"
assert_contains "symlinked dir with trailing slash refused" "line 1: skip (symlink)" "$out"
assert_file "symlink target content intact" "$OUT/tree/keep.md"
ln -s "$OUT" "$H/captures/k2"
out="$(run_list "$H/captures/k2/raw/s.jsonl")"
assert_contains "symlinked parent refused" "line 1: skip (path runs through a symlink)" "$out"
assert_file "file behind the symlinked parent intact" "$OUT/raw/s.jsonl"

echo "== a hash mismatch refuses the whole list"
printf '%s\n' "$B/knowledge/topics/scoped.md" > "$W/targets"
good="$(sha "$W/targets")"
printf '%s\n' "$B/knowledge/topics/scoped.md" "$B/knowledge/clients/wmb" > "$W/targets"
out="$(pd --list "$W/targets" --from-file "$W/from" --sha "$good" --apply 2>&1)"; rc=$?
assert_exit "mismatch -> exit 1" 1 "$rc"
assert_contains "mismatch named" "do not hash to the approved sha256" "$out"
assert_file "nothing deleted on mismatch" "$B/knowledge/topics/scoped.md"
assert_eq "nothing staged on mismatch" "0" "$(staged)"

echo "== dry run (the default) changes nothing"
printf '%s\n' "$B/knowledge/clients/wmb" > "$W/targets"
out="$(pd --list "$W/targets" --from-file "$W/from" --sha "$(sha "$W/targets")")"
assert_contains "dry run says would delete" "line 1: would delete (tree)" "$out"
assert_file "dry run deleted nothing" "$B/knowledge/clients/wmb/sub/a.md"

echo "== a literal backslash name is matched literally (git pathspec glob would hit xy.md)"
out="$(run_list "$B/knowledge/topics/x\\y.md")"
assert_contains "scoped backslash file deleted" "line 1: deleted (scoped)" "$out"
assert_file "the different-scope sibling xy.md survives" "$B/knowledge/topics/xy.md"
if git -C "$B" ls-files --error-unmatch -- knowledge/topics/xy.md >/dev/null 2>&1; then t_ok "xy.md still tracked"; else t_fail "xy.md was staged for deletion"; fi
git -C "$B" commit -qm "drop x\\y"

echo "== the allowed deletions"
mkdir -p "$B/.bailiwick-inbox/raw" "$T_SANDBOX/repo/.bailiwick-outputs/raw"
echo i > "$B/.bailiwick-inbox/raw/s.jsonl"; echo c > "$H/captures/k1/raw/s1.jsonl"
echo r > "$T_SANDBOX/repo/.bailiwick-outputs/raw/s2.md"; echo u > "$B/knowledge/clients/wmb/untracked.md"
out="$(run_list \
  "$B/knowledge/clients/wmb/" \
  "$B/definitions/clients/wmb" \
  "$B/knowledge/topics/scoped.md" \
  "$B/.bailiwick-inbox/raw/s.jsonl" \
  "$H/captures/k1/raw/s1.jsonl" \
  "$T_SANDBOX/repo/.bailiwick-outputs/raw/s2.md")"
assert_contains "summary" "purge_delete: 6 deleted, 0 failed, 0 skipped" "$out"
assert_no_file "client tree gone (tracked)" "$B/knowledge/clients/wmb/sub/a.md"
assert_no_file "client tree gone (untracked)" "$B/knowledge/clients/wmb/untracked.md"
assert_no_file "definitions gone" "$B/definitions/clients/wmb/spec.drawio"
assert_no_file "matching-scope topic gone" "$B/knowledge/topics/scoped.md"
assert_no_file "inbox file gone" "$B/.bailiwick-inbox/raw/s.jsonl"
assert_no_file "central capture gone" "$H/captures/k1/raw/s1.jsonl"
assert_no_file "local raw capture gone" "$T_SANDBOX/repo/.bailiwick-outputs/raw/s2.md"
assert_eq "tracked deletions staged" "3" "$(staged)"
assert_file "other client still intact" "$B/knowledge/clients/other/b.md"

echo "== every curate gather/retire capture location is deletable, one file per enumerated dir"
R="$T_SANDBOX/repo/.bailiwick-outputs"
mkdir -p "$R/.curated" "$R/raw/.curated" "$H/captures/k1/.curated" "$H/captures/k1/raw/.curated"
echo l > "$R/learn-20261018-100000.md"; echo c > "$R/.curated/old.md"; echo c > "$R/raw/.curated/s3.jsonl"
echo l > "$H/captures/k1/learn-20261018-100000.md"; echo c > "$H/captures/k1/.curated/m.md"
echo c > "$H/captures/k1/raw/.curated/s4.jsonl"
out="$(run_list \
  "$R/learn-20261018-100000.md" \
  "$R/.curated/old.md" \
  "$R/raw/.curated/s3.jsonl" \
  "$H/captures/k1/learn-20261018-100000.md" \
  "$H/captures/k1/.curated/m.md" \
  "$H/captures/k1/raw/.curated/s4.jsonl")"; rc=$?
assert_exit "new capture roots -> exit 0" 0 "$rc"
assert_contains "new capture roots summary" "purge_delete: 6 deleted, 0 failed, 0 skipped" "$out"
assert_no_file "seeded manual/learn capture gone" "$R/learn-20261018-100000.md"
assert_no_file "seeded curated manual capture gone" "$R/.curated/old.md"
assert_no_file "seeded curated raw capture gone" "$R/raw/.curated/s3.jsonl"
assert_no_file "central manual/learn capture gone" "$H/captures/k1/learn-20261018-100000.md"
assert_no_file "central curated manual capture gone" "$H/captures/k1/.curated/m.md"
assert_no_file "central curated raw capture gone" "$H/captures/k1/raw/.curated/s4.jsonl"

echo "== deeper nesting, a missing <key>, a nested .bailiwick-outputs, other extensions are refused"
mkdir -p "$R/raw/sub" "$R/raw/.curated/sub" "$R/raw/.bailiwick-outputs" "$H/captures/k1/raw/sub" \
  "$H/captures/k1/sub" "$H/captures/k1/.curated/.curated"
neg="$R/raw/sub/deep.jsonl $R/raw/.curated/sub/deep.md $R/raw/.bailiwick-outputs/nested.md $R/notes.txt
$H/captures/k1/raw/sub/deep.jsonl $H/captures/k1/sub/deep.md $H/captures/k1/.curated/.curated/x.md $H/captures/top.md"
for f in $neg; do echo keep > "$f"; done
# shellcheck disable=SC2086  # split on whitespace: the sandbox paths hold none
out="$(run_list $neg)"; rc=$?
assert_exit "refused capture paths -> exit 0" 0 "$rc"
assert_contains "all eight refused" "purge_delete: 0 deleted, 0 failed, 8 skipped" "$out"
n=0; for f in $neg; do n=$((n + 1)); assert_contains "negative line $n refused" "line $n: skip (outside allowed roots)" "$out"; assert_file "negative line $n intact" "$f"; done

echo "== a failed deletion is reported as FAILED, exits 3, and names no path"
git -C "$B" commit -qm "drop wmb"
mkdir -p "$B/knowledge/clients/acme"; echo a > "$B/knowledge/clients/acme/a.md"
git -C "$B" add -A && git -C "$B" commit -qm "add acme"
echo modified >> "$B/knowledge/clients/acme/a.md"   # git rm refuses a file with local changes
printf 'acme\n' > "$W/from-acme"
printf '%s\n' "$B/knowledge/clients/acme" > "$W/targets"
out="$(pd --list "$W/targets" --from-file "$W/from-acme" --sha "$(sha "$W/targets" "$W/from-acme")" --apply 2>&1)"; rc=$?
assert_exit "failed deletion -> exit 3" 3 "$rc"
assert_contains "FAILED line with reason class" "line 1: FAILED (tree: git rm refused" "$out"
assert_contains "summary counts the failure" "purge_delete: 0 deleted, 1 failed, 0 skipped" "$out"
assert_contains "STOP named" "STOP: 1 line(s) FAILED" "$out"
assert_not_contains "no client name in output" "acme" "$out"
assert_not_contains "no path in output" "knowledge/" "$out"
assert_file "refused file still on disk" "$B/knowledge/clients/acme/a.md"

echo "== the approval hash binds the from-file too; --print-sha prints it; no temp dir is left"
export TMPDIR="$T_SANDBOX/tmp"; mkdir -p "$TMPDIR"
printf '%s\n' "$B/knowledge/clients/acme" > "$W/targets"
assert_eq "--print-sha matches the documented formula" "$(sha "$W/targets" "$W/from-acme")" \
  "$(pd --list "$W/targets" --from-file "$W/from-acme" --print-sha)"
good="$(sha "$W/targets" "$W/from-acme")"
printf 'other\n' > "$W/from-acme"   # the from-file changed after approval
out="$(pd --list "$W/targets" --from-file "$W/from-acme" --sha "$good" --apply 2>&1)"; rc=$?
assert_exit "changed from-file -> exit 1" 1 "$rc"
assert_contains "changed from-file named as a mismatch" "do not hash to the approved sha256" "$out"
pd --list "$W/targets" --from-file "$W/from-acme" --print-sha --apply >/dev/null 2>&1; rc=$?
assert_exit "--print-sha with --apply -> usage" 2 "$rc"
assert_eq "private temp dirs cleaned up" "0" "$(find "$TMPDIR" -mindepth 1 | wc -l | tr -d ' ')"
unset TMPDIR

echo "== bad <from> and a malformed sha are refused"
printf 'wmb/../other\n' > "$W/from-bad"
out="$(pd --list "$W/targets" --from-file "$W/from-bad" --sha "$(sha "$W/targets" "$W/from-bad")" --apply 2>&1)"; rc=$?
assert_exit "bad from -> exit 1" 1 "$rc"
pd --list "$W/targets" --from-file "$W/from" --sha nothex --apply >/dev/null 2>&1; rc=$?
assert_exit "malformed sha -> usage" 2 "$rc"

t_summary
