"""Execute the freshness URL policy against host/path confusion and broken registries."""

import json
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parent.parent
CHECKER = ROOT / "skills/curate/scripts/check_source.py"
REGISTRY = ROOT / "skills/curate/references/gcp-sources.json"


def run(*urls, registry=None):
    args = [sys.executable, str(CHECKER)]
    if registry is not None:
        args += ["--registry", str(registry)]
    return subprocess.run(args + list(urls), capture_output=True, text=True)


def test_all_registered_discovery_urls_are_allowed():
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    for source in data["sources"]:
        result = run(*source["discovery_urls"])
        assert result.returncode == 0, result.stderr
        assert all(source["id"] in row["source_ids"] for row in json.loads(result.stdout))


def test_canonical_and_legacy_urls_have_same_policy():
    result = run(
        "https://docs.cloud.google.com/kubernetes-engine/docs/concepts/workload-identity#overview",
        "https://cloud.google.com/kubernetes-engine/docs/concepts/workload-identity",
    )
    assert result.returncode == 0, result.stderr
    assert [row["source_ids"] for row in json.loads(result.stdout)] == [["gke"], ["gke"]]


@pytest.mark.parametrize("url", [
    "http://docs.cloud.google.com/iam/docs/release-notes",
    "https://docs.cloud.google.com.evil.test/iam/docs/release-notes",
    "https://evil.test/iam/docs/release-notes",
    "https://docs.cloud.google.com@evil.test/iam/docs/release-notes",
    "https://evil@docs.cloud.google.com/iam/docs/release-notes",
    "https://docs.cloud.google.com:443/iam/docs/release-notes",
    "https://docs.cloud.google.com./iam/docs/release-notes",
    "https://docs.cloud.google.com/iam/docs-other/page",
    "https://docs.cloud.google.com/iam/docs/../../blog/post",
    "https://docs.cloud.google.com/iam/docs/./page",
    "https://docs.cloud.google.com/iam/docs/%2e%2e/blog",
    "https://docs.cloud.google.com/iam/docs/%252e%252e/blog",
    "https://docs.cloud.google.com/iam/docs//page",
    "https://docs.cloud.google.com/iam/docs/\\../../blog",
    "https://docs.cloud.google.com/iam/docs/release-notes?redirect=https://evil.test",
    "https://docs.cloud.google.com/iam/docs/release-notes?",
    "https://docs.cloud.google.com/iam/docs/release-notes\n",
    "https://cloud.google.com/blog/products/identity-security/example",
    "https://docs.cloud.google.com/secret-manager/docs/release-notes",
    "https://[invalid/iam/docs/",
])
def test_unsafe_or_out_of_scope_urls_are_denied(url):
    result = run(url)
    assert result.returncode == 1, result.stderr
    assert json.loads(result.stdout)[0]["allowed"] is False


def test_mixed_batch_is_not_reported_as_allowed():
    result = run("https://docs.cloud.google.com/iam/docs/release-notes", "https://evil.test/")
    assert result.returncode == 1
    assert [r["allowed"] for r in json.loads(result.stdout)] == [True, False]


@pytest.mark.parametrize("mutation", ["empty", "duplicate", "outside", "bad-host", "bad-type", "version"])
def test_broken_registry_is_distinct_from_denied_url(tmp_path, mutation):
    data = json.loads(REGISTRY.read_text(encoding="utf-8"))
    if mutation == "empty":
        data["sources"] = []
    elif mutation == "duplicate":
        data["sources"].append(data["sources"][0])
    elif mutation == "outside":
        data["sources"][0]["discovery_urls"] = ["https://evil.test/"]
    elif mutation == "bad-host":
        data["sources"][0]["allowed_prefixes"] = ["https://evil.test/"]
    elif mutation == "bad-type":
        data["sources"][0]["allowed_prefixes"] = "https://docs.cloud.google.com/"
    else:
        data["version"] = 2
    registry = tmp_path / "sources.json"
    registry.write_text(json.dumps(data), encoding="utf-8")
    result = run("https://docs.cloud.google.com/iam/docs/release-notes", registry=registry)
    assert result.returncode == 2, result.stdout
    assert "invalid source registry" in result.stderr


def test_unreadable_or_malformed_registry_fails_closed(tmp_path):
    registry = tmp_path / "missing.json"
    assert run("https://docs.cloud.google.com/iam/docs/", registry=registry).returncode == 2
    registry.write_text("{", encoding="utf-8")
    assert run("https://docs.cloud.google.com/iam/docs/", registry=registry).returncode == 2
