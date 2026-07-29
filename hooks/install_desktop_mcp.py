#!/usr/bin/env python3
"""Safely merge the bailiwick-knowledge MCP filesystem server into a
Claude Desktop / ChatGPT Desktop config file.

Usage: install_desktop_mcp.py <config.json> <knowledge-root>

Both apps use the same top-level `mcpServers` JSON shape, so one script serves
both — the caller just passes the right path per app. Idempotent and
non-destructive: only sets/refreshes the single `bailiwick-knowledge` entry,
preserving every other key and every other MCP server already configured
there. Refuses to touch the file on invalid/non-object JSON (exits 1, changes
nothing) rather than risk clobbering a hand-edited config.

SCOPE, stated precisely — least privilege applies to the ROOT, not the verbs.
The root passed in should be $BAILIWICK/knowledge only (never the whole
framework), so the desktop apps cannot reach hooks, skills, or captures. But
`@modelcontextprotocol/server-filesystem` is READ-WRITE within whatever root it
is given: it exposes write_file/edit_file/move_file/create_directory. Combined
with the fact that desktop apps have no hook system — no capture, no curation
gate, no guardrails (see CLAUDE.md "Non-Negotiable Rules") — this wiring is a
surface that CAN modify the knowledge library outside every gate the framework
otherwise enforces. Treat it as a reference channel by convention, not by
permission, and do not describe it as read-only.

Prints exactly one of: INSTALLED | PRESENT | ERROR: <msg>
Exit 0 on INSTALLED/PRESENT; non-zero on ERROR.
"""
import json
import os
import sys

SERVER_NAME = "bailiwick-knowledge"


def main():
    if len(sys.argv) != 3:
        print("usage: install_desktop_mcp.py <config.json> <knowledge-root>", file=sys.stderr)
        return 2
    dest, root = sys.argv[1], sys.argv[2]

    try:
        if os.path.exists(dest) and os.path.getsize(dest) > 0:
            data = json.load(open(dest, encoding="utf-8"))
        else:
            data = {}
    except Exception as e:
        print(f"ERROR: invalid JSON in {dest} ({e}) — left untouched")
        return 1
    if not isinstance(data, dict):
        print(f"ERROR: top-level JSON in {dest} is not an object — left untouched")
        return 1

    servers = data.get("mcpServers")
    if servers is None:
        servers = data["mcpServers"] = {}
    elif not isinstance(servers, dict):
        print(f"ERROR: 'mcpServers' in {dest} is not an object — left untouched")
        return 1
    desired = {
        "command": "npx",
        "args": ["-y", "@modelcontextprotocol/server-filesystem", root],
    }
    if servers.get(SERVER_NAME) == desired:
        print("PRESENT")
        return 0

    servers[SERVER_NAME] = desired
    os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
    with open(dest, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    print("INSTALLED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
