#!/usr/bin/env bash
# bailiwick — shared config/identity primitives (sourced helper; best-effort, NEVER fails the caller).
#
# One implementation for the four things every hook was reimplementing on its own — the
# .bailiwick-sync.json scalar read (six independent copies existed, three styles), the boolean
# read, the machine-token normalization (four identical tr pipelines, one of which drifted in
# python), and the shadow-allowlist gate (two bash copies, one of which drifted from python).
# Same contract as gh_account.sh / health_common.sh: bw_-prefixed, bash-3.2-clean, fail-open.
#
# Source this file, then:
#   bw_cfg_get <key> [default]     # top-level string from <root>/.bailiwick-sync.json
#   bw_cfg_bool <key>              # exit 0 iff the key is boolean true
#   bw_machine_token [name]        # normalized machine token (no arg: config 'machine' or hostname)
#   bw_is_shadow_repo <dir>        # exit 0 iff dir is shadow-activated (env var or allowlist)
#
# BW_CFG_FILE overrides the config path (default: <this clone>/.bailiwick-sync.json).
# python3 is preferred for JSON correctness; a grep/sed line-parse is the degradation path.
# The batch heredoc parsers in capture_backup.sh / doctor.sh intentionally stay separate: they
# read nested objects in ONE python spawn, which per-key calls here would multiply on hot paths.

_BW_CC_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]:-$0}")/.." 2>/dev/null && pwd || echo "")"

bw_cfg_get() {  # <key> [default] — top-level string value, or default/empty
  _bw_cc_cfg="${BW_CFG_FILE:-$_BW_CC_ROOT/.bailiwick-sync.json}"
  _bw_cc_val=""
  if [ -f "$_bw_cc_cfg" ]; then
    if command -v python3 >/dev/null 2>&1; then
      _bw_cc_val="$(python3 -c 'import json,sys
try: d=json.load(open(sys.argv[1]))
except Exception: d={}
v=d.get(sys.argv[2]); print(v if isinstance(v,str) else "")' "$_bw_cc_cfg" "$1" 2>/dev/null || true)"
    else
      _bw_cc_val="$(grep -oE "\"$1\"[[:space:]]*:[[:space:]]*\"[^\"]+\"" "$_bw_cc_cfg" 2>/dev/null \
        | head -1 | sed -E 's/.*"([^"]+)"$/\1/' || true)"
    fi
  fi
  printf '%s' "${_bw_cc_val:-${2:-}}"
}

bw_cfg_bool() {  # <key> — exit 0 iff boolean true
  _bw_cc_cfg="${BW_CFG_FILE:-$_BW_CC_ROOT/.bailiwick-sync.json}"
  [ -f "$_bw_cc_cfg" ] || return 1
  if command -v python3 >/dev/null 2>&1; then
    [ "$(python3 -c 'import json,sys
try: print(str(json.load(open(sys.argv[1])).get(sys.argv[2],False)).lower())
except Exception: print("false")' "$_bw_cc_cfg" "$1" 2>/dev/null || echo false)" = "true" ]
  else
    grep -qE "\"$1\"[[:space:]]*:[[:space:]]*true" "$_bw_cc_cfg" 2>/dev/null
  fi
}

bw_machine_token() {  # [name] — lowercase, space -> '-', DELETE everything else.
  # THE single bash implementation; capture_session.py / guardrails.py mirror it byte-identically
  # (pinned by tests/test_capture_session.py). No arg: config 'machine', falling back to hostname.
  _bw_cc_name="${1:-}"
  [ -n "$_bw_cc_name" ] || _bw_cc_name="$(bw_cfg_get machine)"
  [ -n "$_bw_cc_name" ] || _bw_cc_name="$(hostname 2>/dev/null || echo unknown)"
  printf '%s' "$_bw_cc_name" | tr '[:upper:] ' '[:lower:]-' | tr -cd 'a-z0-9._-'
}

bw_is_shadow_repo() {  # <dir> — exit 0 iff shadow-activated. Mirror: capture_session.py:is_shadow_repo.
  [ "${BAILIWICK_SHADOW:-}" = "1" ] && return 0
  _bw_cc_list="${BAILIWICK_HOME:-$HOME/.bailiwick}/allowlist"
  [ -f "$_bw_cc_list" ] || return 1
  _bw_cc_here="$( (cd "$1" 2>/dev/null && pwd -P) || echo "$1" )"
  while IFS= read -r _bw_cc_line || [ -n "$_bw_cc_line" ]; do
    _bw_cc_line="${_bw_cc_line%%#*}"
    _bw_cc_line="${_bw_cc_line#"${_bw_cc_line%%[![:space:]]*}"}"
    _bw_cc_line="${_bw_cc_line%"${_bw_cc_line##*[![:space:]]}"}"
    _bw_cc_line="${_bw_cc_line%/}"
    [ -n "$_bw_cc_line" ] || continue
    # Realpath BOTH sides, like the python mirror — a verbatim compare misses symlinked entries.
    _bw_cc_entry="$( (cd "$_bw_cc_line" 2>/dev/null && pwd -P) || echo "$_bw_cc_line" )"
    [ "$_bw_cc_here" = "$_bw_cc_entry" ] && return 0
  done < "$_bw_cc_list"
  return 1
}
