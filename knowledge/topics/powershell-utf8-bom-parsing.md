---
id: powershell-utf8-bom-parsing
type: topic
tags: [powershell, windows, bootstrap, cross-platform, scripting, encoding, pitfall]
confidence: low
last_validated: 2026-07-05
supersedes: []
scope: generic
---

# Topic: Windows PowerShell 5.1 needs a UTF-8 BOM on non-ASCII .ps1

> A cross-platform scripting pitfall: a `.ps1` authored on Linux/macOS (BOM-less UTF-8) can parse
> cleanly under pwsh 7 yet fail hard under Windows PowerShell 5.1.

## The failure
- Windows **PowerShell 5.1** treats a **BOM-less** file as **ANSI/Windows-1252**, not UTF-8. Any
  non-ASCII byte is misread — em dashes (`—`, UTF-8 `E2 80 94`) decode to three cp1252 chars, one of
  which is a **smart quote** that PowerShell parses as a **string delimiter** → cascade
  "Missing closing `}`" / "Unexpected token" errors far from the real spot.
- **pwsh 7** defaults to UTF-8, so the same file parses fine — masking the bug on dev machines.

## The fix
- Ship any `.ps1` containing non-ASCII (em dashes, arrows, accented text, emoji) with a **UTF-8 BOM**
  (`EF BB BF`). Both 5.1 and 7 then read it as UTF-8.
- Or keep the script strictly ASCII. Prefer the BOM — non-ASCII creeps back into comments/strings.

## Verify (don't trust "it runs on my machine")
```bash
head -c3 file.ps1 | xxd            # expect: efbb bf
```
Parse-check on the real interpreters (reachable from WSL via the Windows host binaries):
```
powershell.exe -NoProfile -Command "[System.Management.Automation.Language.Parser]::ParseFile('<win-path>',[ref]$null,[ref]$e)|Out-Null; $e"
```

## Provenance
- Found 2026-07-05 validating `scripts/bootstrap.ps1`: BOM-less → **18 parse errors on
  5.1.26100**, PARSE OK on pwsh 7.6.3; adding the BOM → clean on both. WSL2 reaches the host
  PowerShells at `/mnt/c/.../powershell.exe` and `pwsh.exe` for real parser checks.

## Related
- [Claude MCP wiring](claude-mcp-wiring.md)
