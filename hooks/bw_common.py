"""bailiwick — shared substrate for the python hooks (stdlib-only, fail-safe).

One implementation of the self-gating/health helpers that capture_session.py and guardrails.py
each carried verbatim: the wired-repo gate, the shadow gate, the home resolver, project-dir
resolution, machine-token normalization, and health logging. Both hooks are invoked by absolute
path (``python3 .../hooks/<hook>.py``), so ``sys.path[0]`` is this directory and a plain
``import bw_common`` resolves — the same mechanism capture_backup.sh and session_start.sh
already use for ``repo_key``.

Everything here follows the hook contract: never raise out of a public function; degrade to the
inert answer instead.
"""
import datetime
import json
import os
import re

# The hidden framework complement files that wire a repo (mirrored in bash by
# session_start.sh:is_bailiwick_repo — keep the two lists in step).
COMPLEMENT_FILES = (
    ".bailiwick.local.md",
    "CLAUDE.local.md",
    ".github/instructions/bailiwick.instructions.md",
)


def bw_home():
    """Per-machine global-state root for shadow mode (allowlist + central captures)."""
    return os.environ.get("BAILIWICK_HOME") or os.path.join(os.path.expanduser("~"), ".bailiwick")


def is_bailiwick_repo(project_dir):
    """Seeded gate: a wired repo carries a complement file referencing $BAILIWICK."""
    for name in COMPLEMENT_FILES:
        try:
            with open(os.path.join(project_dir, name), "r", encoding="utf-8", errors="ignore") as fh:
                if "BAILIWICK" in fh.read():
                    return True
        except Exception:
            continue
    return False


def is_shadow_repo(project_dir):
    """Shadow gate: BAILIWICK_SHADOW=1 or a realpath match in the allowlist.

    Mirror of config_common.sh:bw_is_shadow_repo — both realpath BOTH sides.
    """
    if os.environ.get("BAILIWICK_SHADOW") == "1":
        return True
    try:
        here = os.path.realpath(project_dir)
        with open(os.path.join(bw_home(), "allowlist"), "r", encoding="utf-8", errors="ignore") as fh:
            for line in fh:
                entry = line.split("#", 1)[0].strip().rstrip("/")
                if entry and os.path.realpath(entry) == here:
                    return True
    except Exception:
        pass
    return False


def resolve_project_dir(payload):
    """CLAUDE_PROJECT_DIR > payload cwd > getcwd — the chain every hook uses."""
    return (
        os.environ.get("CLAUDE_PROJECT_DIR")
        or (payload.get("cwd") if isinstance(payload, dict) else None)
        or os.getcwd()
    )


def machine_token(name):
    """Byte-identical mirror of config_common.sh:bw_machine_token (tr '[:upper:] ' '[:lower:]-'
    | tr -cd 'a-z0-9._-'): lowercase, space -> '-', DELETE everything else. Divergence splits one
    machine's health shard across two filenames (pinned by tests/test_capture_session.py)."""
    return re.sub(r"[^a-z0-9._-]", "", (name or "").lower().replace(" ", "-"))


def health(component, event, detail):
    """Append one line to this machine's health shard (best-effort, never raises).

    Same JSONL shape and shard path as hooks/health_common.sh:bw_health; transported encrypted
    by capture_backup.sh, aggregated by /metrics.
    """
    try:
        import socket
        machine = ""
        try:
            root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
            with open(os.path.join(root, ".bailiwick-sync.json"), encoding="utf-8") as fh:
                machine = (json.load(fh).get("machine") or "").strip()
        except Exception:
            pass
        machine = machine_token(machine or socket.gethostname()) or "unknown"
        hdir = os.path.join(bw_home(), "health")
        os.makedirs(hdir, exist_ok=True)
        with open(os.path.join(hdir, machine + ".jsonl"), "a", encoding="utf-8") as fh:
            fh.write(json.dumps({
                "ts": datetime.datetime.now().isoformat(timespec="seconds"),
                "machine": machine, "component": component, "event": event,
                "detail": str(detail)[:300]}) + "\n")
    except Exception:
        pass
