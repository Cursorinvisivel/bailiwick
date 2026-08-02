# Tests

The framework's load-bearing plumbing is wiring code — it breaks silently on real machines at
migration time, not in review. These suites execute the contracts CI-side so `scripts/doctor.sh`
only has to catch live-machine drift.

| Suite | Runner | Covers |
|---|---|---|
| `test_guardrails.py` | pytest | Guardrail tier contract (exempt / ask-impact / ask-go-ahead) |
| `test_capture_session.py` | pytest | Capture gating (wired/shadow/inert), `repo_key` collision-resistance, the capture itself via the real hook protocol |
| `test_traffic_counter.py` | pytest | Traffic ledger accumulation |
| `test_install_adapter_hooks.py` | pytest | Codex/Gemini guardrail wiring: managed block/entry only, legacy-marker sweep, refuse-on-malformed |
| `shell/test_capture_backup.sh` | bash | **A capture is never lost**: source survives every failure mode *and* success (only `/curate` purges); unusable key / unreachable remote fail loudly into the health log; ciphertext round-trips back byte-identical; purge is surgical |
| `shell/test_gh_account.sh` | bash | Account resolution (override > map > probe > ambiguous) and per-call token pinning, against a stub `gh` |
| `shell/test_sync_knowledge.sh` | bash | Central/satellite propagation, exit-code contract (2 = PR-less stranding), PR reuse, ADR-009 public-origin refusal |
| `shell/test_doctor.sh` | bash | Every doctor invariant driven to its broken state must ✗ and exit 1 |
| `shell/test_bootstrap.sh` | bash | `--dry-run` writes NOTHING (full state fingerprint); uninstall never un-hides preserved captures; the shadow gate matches symlinked allowlist entries |
| `shell/test_purge_verify.sh` | bash | Deep-removal measurements: history residuals stay loud after a tree purge; preflight blocks while ANY pending capture exists (backup branches, inbox, local staging) |
| `shell/test_public_origin.sh` | bash | ADR-009 Amendment 1: cache hit/expiry/URL-change/malformed-miss, public never cached, timeout fails open without caching — and the critical one: enforcement (`check`) probes LIVE even with a warm cache |
| `shell/test_session_start.sh` | bash | The every-project hook: inert when unwired (not one byte), defaults + index injection when wired, capture nag counts, shadow nag reads central staging |
| `e2e/lifecycle.sh` | bash | Install → doctor → capture → encrypted backup → knowledge sync → ciphertext recovery, each stage feeding the next |

Everything runs sandboxed: own `HOME`, `GNUPGHOME`, `file://` git remotes, and
`shell/stub-bin/gh` on `PATH`. No network, no secrets, no state outside the sandbox.

Run locally:

```bash
python -m pytest tests/ -q     # python contracts
bash tests/shell/run.sh        # shell contracts, run concurrently (each suite also runs standalone)
bash tests/e2e/lifecycle.sh    # end-to-end
```

CI (`.github/workflows/ci.yml`) runs the shell suites on ubuntu **and** macOS — the macOS leg
uses `/bin/bash` 3.2 on purpose: the hooks run under the system bash on user machines, so the
3.2-portability claim is executed there, not just reviewed. A Windows job parses `bootstrap.ps1`
and runs the python contracts under Windows path semantics.
