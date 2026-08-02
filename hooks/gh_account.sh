#!/usr/bin/env bash
# bailiwick — shared GitHub account resolution (sourced helper; best-effort, NEVER fails the caller).
#
# Multi-account machines break bare `gh`: git pushes ride the SSH alias in the remote URL, but the
# API call runs as whatever account is globally ACTIVE — which may not even be able to see the repo.
# The observed failure mode is nasty: `git push` succeeds, `gh pr create` 404s, and satellite
# knowledge strands on `sync/<machine>` with no route to main. This helper picks the right account
# for a given clone and wraps `gh` so every call carries that account's token, resolved lazily from
# gh's keychain at call time — nothing lands in a dotfile or the exported environment, and the pin
# survives `gh auth switch` back to another account for daily work.
#
# Source this file, then:
#   bw_resolve_gh_account <clone-root>   # sets the BW_GH_* globals below
#   bw_gh <gh-args...>                   # run `gh` as the resolved account (bare `gh` fallback)
#
# Globals set: BW_GH_USER (login; empty = unresolved), BW_GH_HOST (real API host), BW_GH_REPO
# (owner/repo), BW_GH_ALIAS (host token in the remote URL, possibly an SSH alias), BW_GH_DECIDED
# (override|account-map|probe|ambiguous|empty), BW_GH_WARN (human-readable warning, may be empty).
#
# Selection priority (single source of truth — bootstrap.sh's MCP wiring delegates here):
#   1. explicit override in <root>/.bailiwick-sync.json: "github_account" (+ optional "github_host")
#   2. "github_account_map"[owner] in the same file — the deterministic, machine-readable form of
#      the gitconfig rewrite-rule intent (gitconfig maps an owner to an SSH *alias*, not a gh
#      *login*, so the bridge is declared here)
#   3. access probe — collect EVERY logged-in account that can read the repo: exactly one wins
#      silently; several is AMBIGUOUS (active account wins + warn, pointing at github_account_map);
#      none leaves BW_GH_USER empty and callers degrade to bare `gh`.
# Set BW_NO_GH_AUTH=1 to skip resolution entirely (CI / token-only setups).

bw_resolve_gh_account() {
  BW_GH_USER=""; BW_GH_HOST=""; BW_GH_REPO=""; BW_GH_ALIAS=""; BW_GH_DECIDED=""; BW_GH_WARN=""
  _bw_root="${1:-}"
  [ "${BW_NO_GH_AUTH:-0}" = "1" ] && return 0
  [ -n "$_bw_root" ] || return 0

  _bw_remote="$(git -C "$_bw_root" remote get-url origin 2>/dev/null || true)"
  [ -n "$_bw_remote" ] || return 0
  _bw_u="${_bw_remote%.git}"
  case "$_bw_u" in
    *://*)  _bw_hp="${_bw_u#*://}"; _bw_hp="${_bw_hp##*@}"; BW_GH_ALIAS="${_bw_hp%%/*}"; BW_GH_REPO="${_bw_hp#*/}" ;;
    *@*:*)  _bw_rest="${_bw_u#*@}"; BW_GH_ALIAS="${_bw_rest%%:*}"; BW_GH_REPO="${_bw_rest#*:}" ;;
    *)      return 0 ;;
  esac
  # An SSH host alias (e.g. github-personal) is not a real hostname — resolve it for the API.
  BW_GH_HOST="$(ssh -G "$BW_GH_ALIAS" 2>/dev/null | awk '/^hostname /{print $2; exit}' || true)"
  case "$BW_GH_HOST" in *.*) : ;; *) BW_GH_HOST="github.com" ;; esac

  _bw_cfg="$_bw_root/.bailiwick-sync.json"
  # Scalar reads delegate to the shared primitive (hooks/config_common.sh); if it is somehow
  # absent the overrides are simply ignored and the access probe below still resolves.
  . "$(dirname "${BASH_SOURCE[0]:-$0}")/config_common.sh" 2>/dev/null || true
  _bw_cfg_get() {  # top-level string value for key $1, or empty
    command -v bw_cfg_get >/dev/null 2>&1 || return 0
    BW_CFG_FILE="$_bw_cfg" bw_cfg_get "$1"
  }
  _bw_cfg_map_get() {  # github_account_map[$1] (python only; degrades to the probe without python3)
    [ -f "$_bw_cfg" ] || return 0
    command -v python3 >/dev/null 2>&1 || return 0
    python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
m=d.get("github_account_map") or {}
v=m.get(sys.argv[2]) if isinstance(m,dict) else None
print(v if isinstance(v,str) else "")' "$_bw_cfg" "$1" 2>/dev/null
  }

  _bw_owner="${BW_GH_REPO%%/*}"
  command -v gh >/dev/null 2>&1 || return 0
  [ -n "$BW_GH_REPO" ] || return 0

  _bw_ovr_acct="$(_bw_cfg_get github_account)"; _bw_ovr_host="$(_bw_cfg_get github_host)"
  _bw_map_acct="$(_bw_cfg_map_get "$_bw_owner")"
  _bw_pick=""; _bw_pick_host="$BW_GH_HOST"
  if [ -n "$_bw_ovr_acct" ]; then
    _bw_pick="$_bw_ovr_acct"; [ -n "$_bw_ovr_host" ] && _bw_pick_host="$_bw_ovr_host"; BW_GH_DECIDED="override"
  elif [ -n "$_bw_map_acct" ]; then
    _bw_pick="$_bw_map_acct"; BW_GH_DECIDED="account-map"
  fi
  if [ -n "$_bw_pick" ]; then
    # Honour the declared choice — it only needs a usable token (no access probe).
    if [ -n "$(gh auth token --hostname "$_bw_pick_host" --user "$_bw_pick" 2>/dev/null || true)" ]; then
      BW_GH_USER="$_bw_pick"; BW_GH_HOST="$_bw_pick_host"
    else
      BW_GH_WARN="configured gh account '$_bw_pick' has no token on $_bw_pick_host (run 'gh auth login' for it) — fell back to the access probe"
      BW_GH_DECIDED=""
    fi
  fi
  if [ -z "$BW_GH_USER" ]; then
    # Access probe — access test (not name match): the owner may be an org whose login differs
    # from your handle.
    _bw_cands="$(gh auth status 2>/dev/null | awk '{for(i=1;i<=NF;i++) if($i=="account") print $(i+1)}' || true)"
    _bw_active_tok="$(gh auth token --hostname "$BW_GH_HOST" 2>/dev/null || true)"
    _bw_matches=""; _bw_active_match=""
    for _bw_acct in $_bw_cands; do
      _bw_tok="$(gh auth token --hostname "$BW_GH_HOST" --user "$_bw_acct" 2>/dev/null || true)"
      [ -n "$_bw_tok" ] || continue
      if GH_TOKEN="$_bw_tok" gh api --hostname "$BW_GH_HOST" "repos/$BW_GH_REPO" >/dev/null 2>&1; then
        _bw_matches="${_bw_matches:+$_bw_matches }$_bw_acct"
        [ -n "$_bw_active_tok" ] && [ "$_bw_tok" = "$_bw_active_tok" ] && _bw_active_match="$_bw_acct"
      fi
    done
    _bw_n=0; for _bw_m in $_bw_matches; do _bw_n=$((_bw_n+1)); done
    if [ "$_bw_n" -eq 1 ]; then
      BW_GH_USER="$_bw_matches"; BW_GH_DECIDED="probe"
    elif [ "$_bw_n" -gt 1 ]; then
      BW_GH_USER="${_bw_active_match:-${_bw_matches%% *}}"; BW_GH_DECIDED="ambiguous"
      BW_GH_WARN="multiple gh accounts can read ${BW_GH_REPO} (${_bw_matches}) — defaulted to '${BW_GH_USER}' (remote uses SSH profile '${BW_GH_ALIAS:-n/a}'). Pin it deterministically by adding to ${_bw_cfg}: \"github_account_map\": { \"${_bw_owner}\": \"<account>\" }"
    fi
  fi
  return 0
}

# Explicit-repo args for gh calls, from the last resolution. Word-split is intentional at the
# call sites (owner/repo cannot contain spaces) — this helper owns that contract so callers
# don't each carry a shellcheck pragma.
bw_gh_repo_args() {  # echoes "--repo <host>/<owner>/<repo>" or nothing
  [ -n "${BW_GH_REPO:-}" ] || return 0
  printf -- '--repo %s/%s' "${BW_GH_HOST:-github.com}" "$BW_GH_REPO"
}

# Open-PR probe for a branch: echoes the PR number, or nothing when none is OPEN. The state
# filter matters — branch names are reused across syncs, so a MERGED/CLOSED PR must not count.
bw_gh_open_pr() {  # <branch>
  _bw_ra="$(bw_gh_repo_args)"
  # shellcheck disable=SC2086  # intentional word-split of the --repo args
  bw_gh pr list $_bw_ra --head "$1" --state open --json number --jq '.[0].number // empty' 2>/dev/null || true
}

# `gh` as the resolved account. Token is re-read from gh's keychain on EVERY call (lazy), so the
# pin keeps working after `gh auth switch`. With no resolution (or no token) this is bare `gh`.
# Known limit: the pin rides GH_TOKEN, which gh honours for github.com; against a GitHub
# Enterprise host gh reads GH_ENTERPRISE_TOKEN instead, so the pin degrades to the active account.
bw_gh() {
  if [ -n "${BW_GH_USER:-}" ] && command -v gh >/dev/null 2>&1; then
    _bw_tok="$(gh auth token --hostname "${BW_GH_HOST:-github.com}" --user "$BW_GH_USER" 2>/dev/null || true)"
    if [ -n "$_bw_tok" ]; then
      GH_TOKEN="$_bw_tok" gh "$@"
      return $?
    fi
  fi
  gh "$@"
}
