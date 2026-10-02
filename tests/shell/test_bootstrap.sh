#!/usr/bin/env bash
# Contract tests for scripts/bootstrap.sh — the layer that writes into OTHER PEOPLE'S repos.
#
# The two invariants pinned here exist because each was silently false once:
#   1. --dry-run writes NOTHING — not the shadow allowlist (which would ACTIVATE the framework),
#      not tracked --with-standards baselines, not an --init directory.
#   2. Uninstall never un-hides preserved plaintext captures: when .bailiwick-outputs/ survives,
#      its .git/info/exclude rule survives with it (the 8e750b8 capture-leak fix).
set -u
. "$(dirname "$0")/lib.sh"
t_sandbox

export GH_STUB_ACCOUNTS="alice"
export GH_STUB_CANREAD="tok_alice"
BOOTSTRAP="$REPO_ROOT/scripts/bootstrap.sh"

new_target() {  # fresh committed git repo to bootstrap against; prints its path
  local d="$T_SANDBOX/target$1"
  mkdir -p "$d"
  git -C "$d" init -q -b main
  echo "x" > "$d/README.md"
  git -C "$d" add -A
  git -C "$d" -c user.name=bw-test -c user.email=test@local commit -qm seed
  printf '%s' "$d"
}

# Full-state fingerprint: every file (path + content hash) under the dirs bootstrap could touch.
state() {
  for d in "$@"; do
    [ -e "$d" ] || continue
    (cd "$d" && find . -type f ! -path './.git/*' -exec md5sum {} \; 2>/dev/null)
  done | sort
}

echo "== --dry-run writes NOTHING (shadow default: would otherwise activate the framework)"
T1="$(new_target 1)"
before="$(state "$T1" "$HOME" "$BAILIWICK_HOME")"
out="$(bash "$BOOTSTRAP" --dry-run "$T1" 2>&1)"; rc=$?
after="$(state "$T1" "$HOME" "$BAILIWICK_HOME")"
assert_exit "dry-run shadow exits 0" 0 "$rc"
assert_eq "no file created or changed anywhere" "$before" "$after"
assert_contains "allowlist addition is PLANNED, not done" "would add" "$out"
assert_no_file "allowlist itself not created" "$BAILIWICK_HOME/allowlist"

echo "== --dry-run --seeded --with-standards writes NOTHING (tracked team files!)"
T2="$(new_target 2)"
before="$(state "$T2" "$HOME" "$BAILIWICK_HOME")"
bash "$BOOTSTRAP" --dry-run --seeded --with-standards "$T2" >/dev/null 2>&1
rc=$?
after="$(state "$T2" "$HOME" "$BAILIWICK_HOME")"
assert_exit "dry-run seeded exits 0" 0 "$rc"
assert_eq "seeded dry-run changed nothing (incl. tracked baselines)" "$before" "$after"
assert_eq "git worktree untouched" "" "$(git -C "$T2" status --porcelain)"

echo "== --dry-run --init creates neither the directory nor a git repo"
bash "$BOOTSTRAP" --dry-run --init "$T_SANDBOX/brand-new" >/dev/null 2>&1
rc=$?
assert_exit "dry-run init exits 0" 0 "$rc"
if [ -e "$T_SANDBOX/brand-new" ]; then t_fail "--dry-run --init created the target dir"; else t_ok "--dry-run --init created nothing"; fi

echo "== seeded for real, then uninstall: captures AND their exclude rule survive"
T3="$(new_target 3)"
bash "$BOOTSTRAP" --seeded "$T3" >/dev/null 2>&1
excl="$T3/.git/info/exclude"
assert_contains "seed wrote the capture exclude rule" ".bailiwick-outputs/" "$excl"
mkdir -p "$T3/.bailiwick-outputs/raw"
echo "PLAINTEXT-TRANSCRIPT" > "$T3/.bailiwick-outputs/raw/s1.jsonl"
out="$(bash "$BOOTSTRAP" --uninstall "$T3" 2>&1)"
assert_file "capture file survives the uninstall" "$T3/.bailiwick-outputs/raw/s1.jsonl"
assert_contains "uninstall says the rule is KEPT" "rule is KEPT" "$out"
assert_contains "exclude rule survives with the captures" ".bailiwick-outputs/" "$excl"
assert_contains "keep-note explains why the rule stayed" "uncurated plaintext captures still present" "$excl"
assert_not_contains "framework marker block itself is gone" "bailiwick framework wiring" "$excl"
assert_eq "the preserved captures stay INVISIBLE to git" "" "$(git -C "$T3" status --porcelain | grep bailiwick-outputs || true)"

echo "== uninstall when the staging dir is GONE removes the rule entirely"
# (while the dir exists — even empty — the rule is deliberately kept; see warn_repo_captures)
T4="$(new_target 4)"
bash "$BOOTSTRAP" --seeded "$T4" >/dev/null 2>&1
rm -rf "$T4/.bailiwick-outputs"
bash "$BOOTSTRAP" --uninstall "$T4" >/dev/null 2>&1
assert_not_contains "no staging dir -> no leftover exclude rule" ".bailiwick-outputs/" "$T4/.git/info/exclude"

echo "== symlinked allowlist entry activates the REAL bash shadow gate (drift regression)"
# The allowlist holds a SYMLINK to the repo; the python hooks always matched it (they realpath
# both sides) but the bash gates compared the entry verbatim and stayed inert — the drift this
# pins. session_start.sh is the real consumer: activated => it emits the defaults banner.
T5="$(new_target 5)"
ln -s "$T5" "$T_SANDBOX/link-to-t5"
mkdir -p "$BAILIWICK_HOME"
printf '%s\n' "$T_SANDBOX/link-to-t5" > "$BAILIWICK_HOME/allowlist"
out="$(CLAUDE_PROJECT_DIR="$T5" bash "$REPO_ROOT/hooks/session_start.sh" 2>/dev/null)"
assert_contains "session_start activates via the symlinked entry" "Framework defaults active" "$out"
out="$(CLAUDE_PROJECT_DIR="$T_SANDBOX/targetX-unlisted" bash "$REPO_ROOT/hooks/session_start.sh" 2>/dev/null)"
assert_eq "unlisted dir stays inert" "" "$out"
rm -f "$BAILIWICK_HOME/allowlist"

# ---- --role: restoring a machine's sync role -------------------------------------------------------
# .bailiwick-sync.json is gitignored, so a reinstalled central came back as a satellite with nothing
# saying so. --role writes the role into the CLONE the script lives in — run from a sandbox copy so
# the real checkout's config is never touched.
RI="$T_SANDBOX/role-inst"; mkdir -p "$RI/scripts"
cp "$BOOTSTRAP" "$RI/scripts/"; cp "$REPO_ROOT/.bailiwick-sync.example.json" "$RI/"
RCFG="$RI/.bailiwick-sync.json"
role_of() { python3 -c 'import json,sys; d=json.load(open(sys.argv[1])); print(d.get(sys.argv[2],""))' "$RCFG" "$1"; }

echo "== --role --dry-run writes nothing"
out="$(bash "$RI/scripts/bootstrap.sh" --role central --machine box1 --dry-run 2>&1)"; rc=$?
assert_exit "dry-run role exits 0" 0 "$rc"
assert_no_file "no config written under --dry-run" "$RCFG"
assert_contains "dry-run says what it would do" "[dry-run] would have created" "$out"

echo "== --role central on a machine with NO config creates it (the reinstall case)"
out="$(bash "$RI/scripts/bootstrap.sh" --role central --machine box1 2>&1)"; rc=$?
assert_exit "standalone --role exits 0" 0 "$rc"
assert_file "config created" "$RCFG"
assert_eq "role is central" "central" "$(role_of role)"
assert_eq "machine set" "box1" "$(role_of machine)"
assert_eq "example's placeholder backup is NOT enabled" "False" \
  "$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["capture_backup"]["enabled"])' "$RCFG")"
assert_contains "reports the change" "role: satellite (default) -> central" "$out"

echo "== --role on an existing config changes ONLY role, preserving everything else"
python3 - "$RCFG" <<'PY'
import json, sys
d = json.load(open(sys.argv[1])); d["github_account"] = "pinned-user"; d["capture_backup"]["repo"] = "git@x:y/z.git"
json.dump(d, open(sys.argv[1], "w"), indent=2)
PY
out="$(bash "$RI/scripts/bootstrap.sh" --role satellite 2>&1)"; rc=$?
assert_exit "demote exits 0" 0 "$rc"
assert_eq "role demoted" "satellite" "$(role_of role)"
assert_eq "machine kept without --machine" "box1" "$(role_of machine)"
assert_eq "gh pin preserved" "pinned-user" "$(role_of github_account)"
assert_contains "backup repo preserved" "git@x:y/z.git" "$RCFG"

echo "== bad input is refused before anything is written"
before="$(cat "$RCFG")"
out="$(bash "$RI/scripts/bootstrap.sh" --role primary 2>&1)"; rc=$?
assert_exit "unknown role -> exit 2" 2 "$rc"
out="$(bash "$RI/scripts/bootstrap.sh" --role 2>&1)"; rc=$?
assert_exit "--role without a value -> exit 2" 2 "$rc"
out="$(bash "$RI/scripts/bootstrap.sh" --machine box2 --install-tools --dry-run 2>&1)"; rc=$?
assert_exit "--machine without --role -> exit 2" 2 "$rc"
assert_eq "config untouched by refused runs" "$before" "$(cat "$RCFG")"

echo "== an unparseable config is refused, never overwritten"
echo '{ broken' > "$RCFG"
out="$(bash "$RI/scripts/bootstrap.sh" --role central 2>&1)"; rc=$?
assert_exit "invalid JSON -> exit 2" 2 "$rc"
assert_eq "broken file left as-is" "{ broken" "$(cat "$RCFG")"

t_summary
