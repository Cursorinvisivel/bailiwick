#!/usr/bin/env python3
"""Check freshness evidence URLs against the bundled GCP source policy; no network I/O.

Exit 0: all allowed; 1: at least one denied; 2: invalid registry or invocation.
This validates supplied URLs, not a web tool's undisclosed redirect chain.
"""

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit


REGISTRY = Path(__file__).resolve().parent.parent / "references" / "gcp-sources.json"
# Allowlist, not blocklist: servers normalize forms like "..;" into traversal (observed live).
SEGMENT = re.compile(r"[A-Za-z0-9][A-Za-z0-9._~-]*")
# Registry prefixes must name a product docs tree, never a whole host.
PREFIX_PATH = re.compile(r"(/[a-z0-9-]+)+/docs/")


def parse_url(url):
    """Reject URL forms that tools/servers may normalize differently."""
    if not isinstance(url, str) or not url or len(url) > 8192:
        raise ValueError("expected a nonempty URL of at most 8192 characters")
    if any(ord(c) <= 32 or ord(c) >= 127 for c in url) or "\\" in url:
        raise ValueError("non-ASCII, whitespace, control characters or backslashes")
    parts = urlsplit(url)
    if parts.scheme != "https" or not parts.hostname:
        raise ValueError("HTTPS and an exact hostname are required")
    if parts.username is not None or parts.password is not None or ":" in parts.netloc:
        raise ValueError("credentials and explicit ports are forbidden")
    if parts.query or "?" in url:
        raise ValueError("query strings are not permitted by this policy")
    if parts.fragment or "#" in url:
        raise ValueError("fragments are not permitted by this policy")
    path = parts.path or "/"
    segments = path.split("/")[1:]
    if segments and segments[-1] == "":
        segments.pop()
    if not all(SEGMENT.fullmatch(segment) for segment in segments):
        raise ValueError("encoded or ambiguous paths are forbidden")
    return parts.hostname, path


def matching_sources(url, sources):
    host, path = parse_url(url)
    matches = []
    for source in sources:
        for prefix in source["allowed_prefixes"]:
            prefix_host, prefix_path = parse_url(prefix)
            base = prefix_path.rstrip("/")
            if host == prefix_host and (path == base or path.startswith(base + "/")):
                matches.append(source["id"])
                break
    return matches


def load_registry(path):
    data = json.loads(path.read_text(encoding="utf-8"))
    if (not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1
            or data.get("provider") != "gcp"):
        raise ValueError("expected GCP registry version 1")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("expected nonempty sources list")
    seen = set()
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("source must be an object")
        source_id = source.get("id")
        if not isinstance(source_id, str) or not source_id or source_id in seen:
            raise ValueError("source IDs must be nonempty and unique")
        seen.add(source_id)
        for field in ("allowed_prefixes", "discovery_urls", "tags"):
            values = source.get(field)
            if not isinstance(values, list) or not values or not all(isinstance(v, str) and v for v in values):
                raise ValueError(f"{source_id}: expected nonempty {field} string list")
        for prefix in source["allowed_prefixes"]:
            host, prefix_path = parse_url(prefix)
            if (host not in ("docs.cloud.google.com", "cloud.google.com")
                    or not PREFIX_PATH.fullmatch(prefix_path)):
                raise ValueError(f"{source_id}: prefix must be an official Google Cloud documentation URL")
        for url in source["discovery_urls"]:
            if not matching_sources(url, [source]):
                raise ValueError(f"{source_id}: discovery URL outside its allowed prefixes")
    return sources


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("urls", nargs="+")
    args = parser.parse_args(argv)
    try:
        sources = load_registry(args.registry)
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print(f"invalid source registry: {exc}", file=sys.stderr)
        return 2
    results = []
    for url in args.urls:
        try:
            matches = matching_sources(url, sources)
            result = {"url": url, "allowed": bool(matches), "source_ids": matches}
            if not matches:
                result["reason"] = "outside allowed source prefixes"
        except ValueError as exc:
            result = {"url": url, "allowed": False, "source_ids": [], "reason": str(exc)}
        results.append(result)
    print(json.dumps(results, indent=2))
    return 0 if all(result["allowed"] for result in results) else 1


if __name__ == "__main__":
    sys.exit(main())
