<#
  bailiwick project bootstrap (PowerShell).

  Wire a repository to the framework. DEFAULT = SHADOW MODE (FRAMEWORK.md 7.1): zero-footprint,
  personal - NO files are written into the repo; it is opted in via ~/.bailiwick/allowlist
  (BAILIWICK_HOME overrides the root) plus global user-scope MCP. With -Seeded, the wiring is
  written INTO the repo instead - MCP configs (Claude Code + VS Code), framework guidance as
  HIDDEN COMPLEMENT files (CLAUDE.local.md, optional .bailiwick.local.md Codex marker / Copilot
  instructions; the team's own CLAUDE.md/AGENTS.md/copilot-instructions.md are never touched or
  shadowed), capture-staging - all excluded LOCALLY via .git/info/exclude, never the tracked
  .gitignore, so nothing about the framework is shared with colleagues or clients who clone the
  repo. .bailiwick-outputs/ (unsanitised captures) is always kept local. -WithStandards seeds the TRACKED
  team baselines and works in BOTH modes (it is the intentional shared path).

  Works for a fresh repo (-Init, implies -Seeded) or an existing clone. Point it at any path.

  Usage:
    pwsh scripts/bootstrap.ps1 [-Seeded|-Shadow] [-Init] [-WithAgents] [-WithCopilot] [-WithGemini] [-AllTools]
                               [-WithStandards] [-Update] [-Visible] [-Force] [-Clobber] [-NoGhAuth]
                               [-InstallTools] [-WithDesktop] [-DryRun] <target-repo-path>
    pwsh scripts/bootstrap.ps1 -InstallTools [-WithDesktop]                 (global-only: no target repo needed)
    pwsh scripts/bootstrap.ps1 -Uninstall [-DryRun]                        (remove global wiring; bailiwick-scoped)
    pwsh scripts/bootstrap.ps1 -Uninstall <repo> [-PurgeCaptures] [-DryRun]  (un-seed one repo; captures preserved)

  Modes (SHADOW is the DEFAULT):
  (no mode flag) SHADOW MODE: activates the framework for <repo> WITHOUT writing ANY files into
  it. Adds the repo root to ~/.bailiwick/allowlist and registers global user-scope MCP (Claude
  Code); captures stage centrally under ~/.bailiwick/captures/. With -WithAgents / -WithGemini
  it ALSO injects global Codex / Gemini MCP (~/.codex/config.toml, ~/.gemini/settings.json; bailiwick-*
  names, idempotent). -WithStandards still seeds the TRACKED team baselines; other seeding /
  exclude flags are ignored. Undo: delete the repo's line from the allowlist.
  -Shadow is an explicit alias for the default shadow mode (kept for compatibility; no-op).
  -Seeded is the in-repo hidden variant described above; implied by -Visible and -Init (they
  write repo files by design).

  -NoGhAuth skips the gh CLI probe (no network call): always writes the github MCP server
  in its ${GITHUB_TOKEN} env-var form. Use for offline / CI runs.
  -InstallTools installs missing once-per-machine prerequisites: terraform-mcp-server and github-mcp-server (go install),
  the capture/curation + guardrail hooks (merged into ~/.claude/settings.json), the global Claude
  skill symlinks (~/.claude/skills/: /curate, /enrich, /learn, /metrics, /investigate, /purge, /sign), the Quality Workflow
  stages as native Claude Code subagents (~/.claude/agents/: bailiwick-implement, bailiwick-quality, ... - ADR-010), the Codex skill symlinks
  (~/.codex/skills/: bailiwick-curate, bailiwick-enrich, bailiwick-learn, bailiwick-investigate, bailiwick-purge), and the global Codex + Gemini operator layers
  (managed blocks in ~/.codex/AGENTS.md and ~/.gemini/GEMINI.md). Idempotent; off by default.
  Run with NO <target-repo-path> for a global-only install (nothing per-repo is written).
  -WithGemini generates .gemini/settings.json (Gemini MCP + advisory excludeTools) and seeds the
  shared .bailiwick.local.md marker; a team-tracked .gemini/settings.json is left untouched.
  -WithAgents seeds .bailiwick.local.md (Codex private marker, read via the global ~/.codex/AGENTS.md
  layer; the team's own AGENTS.md is never shadowed).
  -Update: with -Seeded, regenerates the MANAGED configs and reconciles .git/info/exclude,
  while preserving hand-edited complements; in (default) shadow mode it refreshes
  the allowlist + global MCP wiring idempotently. With -WithStandards it PATCHES IN PLACE only the
  'Working intelligence' reuse-rule section of existing baseline files.
  -DryRun previews every global-config and repo-file change (install OR uninstall) and writes
  NOTHING. Combine with any other flags.
  -Uninstall reverses framework wiring. With NO target: the once-per-machine GLOBAL wiring - Bailiwick's
  hook entries in ~/.claude/settings.json, its Codex/Gemini guardrail + MCP blocks and operator layers,
  the skill symlinks, user-scope MCP, and the shadow allowlist. With a TARGET repo ('-Uninstall <repo>'):
  un-seeds THAT repo - removes the seeded complement/MCP files (untracked + this clone's), strips the
  framework's own .git/info/exclude block, and drops the repo's allowlist line. Strictly bailiwick-scoped:
  tracked team files, -WithStandards baselines, a coexisting framework, and captures are never touched.
  Your captures/health/audit data and go-installed MCP binaries are left in place. Preview it with -DryRun.
  -PurgeCaptures (only with '-Uninstall <repo>') also deletes that repo's .bailiwick-outputs/ INCLUDING
  any uncurated captures (default is to preserve + warn). Irreversible.
  -WithDesktop (only with -InstallTools): wire a knowledge-SCOPED 'bailiwick-knowledge' MCP filesystem server -
  rooted at knowledge/ ONLY, never the rest of the framework, read-write WITHIN that root (no hooks/gates;
  reference-by-convention) - into Claude Desktop and
  ChatGPT Desktop's own MCP config, so either app can CONSULT the knowledge library outside a coding
  session. Both apps sit OUTSIDE the four hook-adapters (no hook system, so no capture/curation/guardrails).
  Auto-detects the macOS/Windows config paths; idempotent (delegates the merge to install_desktop_mcp.py).
  Pair it with knowledge/templates/desktop-reference-instructions.md - paste that into each app's
  Project/custom instructions. The bash bootstrap.sh exposes the same flag as --with-desktop.
#>
[CmdletBinding()]
param(
  [Parameter(Position = 0)][string]$Target,
  [switch]$Init,
  [switch]$WithAgents,
  [switch]$WithCopilot,
  [switch]$WithGemini,
  [switch]$AllTools,
  [switch]$WithStandards,
  [switch]$Update,
  [switch]$Visible,
  [switch]$Force,
  [switch]$Clobber,
  [switch]$NoGhAuth,
  [switch]$InstallTools,
  [switch]$Shadow,
  [switch]$Seeded,
  [switch]$DryRun,
  [switch]$Uninstall,
  [switch]$PurgeCaptures,
  [switch]$WithDesktop,
  [switch]$Help
)

$ErrorActionPreference = 'Stop'

# Return a clean, normalized NATIVE filesystem path. Windows PowerShell 5.1 prefixes paths under a
# UNC root (e.g. a \\wsl$\... repo) with the provider qualifier 'Microsoft.PowerShell.Core\FileSystem::'
# and does not collapse '..' — both would poison the allowlist entry and the MCP filesystem root. Strip
# the qualifier and normalize. GetFullPath needs no filesystem access and handles UNC + '..'.
function Get-NativePath([string]$p) {
  if ([string]::IsNullOrEmpty($p)) { return $p }
  $p = $p -replace '^Microsoft\.PowerShell\.Core\\FileSystem::', ''
  try { return [System.IO.Path]::GetFullPath($p) } catch { return $p }
}

$BailiwickRoot = Get-NativePath (Join-Path $PSScriptRoot '..')
$CanonPath = '/path/to/bailiwick'   # path baked into committed templates

# ================================ dry-run + uninstall ===========================================
function Dry { return $DryRun }
function Plan([string]$msg) { Write-Host "  [dry-run] would $msg" }

# Remove a marker-delimited BEGIN..END block from a text file, in place. Only ever matches
# 'bailiwick' markers, so a coexisting framework's blocks are never touched. Best-effort.
function Remove-MarkerBlock([string]$file, [string]$begin, [string]$end, [string]$label) {
  if (-not (Test-Path $file)) { return }
  $cur = [System.IO.File]::ReadAllText($file)
  if ($cur -notlike "*$begin*") { return }
  if (Dry) { Plan "remove the $label block from $file"; return }
  $pat = [regex]::Escape($begin) + '.*?' + [regex]::Escape($end) + '[^\r\n]*'
  $new = [System.Text.RegularExpressions.Regex]::Replace(
    $cur, $pat, '', [System.Text.RegularExpressions.RegexOptions]::Singleline)
  $new = $new -replace "(\r?\n){3,}", "`n`n"
  [System.IO.File]::WriteAllText($file, $new)
  Write-Host "  removed: $label block from $file"
}

# Drop only Claude Code hook entries whose command points into THIS clone (path-scoped, so a
# coexisting framework's hooks — a different path — are preserved).
function Remove-ClaudeHooks {
  $f = Join-Path $HOME '.claude/settings.json'
  if (-not (Test-Path $f)) { return }
  $rootFwd = ($BailiwickRoot -replace '\\', '/')
  $raw = [System.IO.File]::ReadAllText($f)
  if ((($raw -replace '\\', '/') -notlike "*$rootFwd*")) { return }
  if (Dry) { Plan "remove this clone's guardrail + capture hook entries from $f"; return }
  try { $d = $raw | ConvertFrom-Json } catch { return }
  if (-not $d.PSObject.Properties['hooks']) { return }
  $hooks = $d.hooks
  foreach ($ev in @($hooks.PSObject.Properties.Name)) {
    $groups = $hooks.$ev
    if ($groups -isnot [array]) { continue }
    $ng = @()
    foreach ($g in $groups) {
      $kept = @()
      foreach ($h in @($g.hooks)) {
        if ((([string]$h.command -replace '\\', '/') -like "*$rootFwd*")) { continue }
        $kept += $h
      }
      if ($kept.Count -gt 0) { $g.hooks = $kept; $ng += $g }
    }
    if ($ng.Count -gt 0) { $hooks.$ev = $ng } else { $hooks.PSObject.Properties.Remove($ev) }
  }
  if (@($hooks.PSObject.Properties.Name).Count -eq 0) { $d.PSObject.Properties.Remove('hooks') }
  [System.IO.File]::WriteAllText($f, (($d | ConvertTo-Json -Depth 20) + "`n"))
  Write-Host "  removed: bailiwick hooks from $f"
}

function Remove-GeminiJson([string]$f) {
  if (-not (Test-Path $f)) { return }
  $raw = [System.IO.File]::ReadAllText($f)
  if ($raw -notlike '*bailiwick-*') { return }
  if (Dry) { Plan "remove bailiwick-guardrail hook + bailiwick-* MCP servers from $f"; return }
  try { $d = $raw | ConvertFrom-Json } catch { return }
  if ($d.PSObject.Properties['mcpServers']) {
    foreach ($k in @($d.mcpServers.PSObject.Properties.Name)) {
      if ($k -like 'bailiwick-*') { $d.mcpServers.PSObject.Properties.Remove($k) }
    }
    if (@($d.mcpServers.PSObject.Properties.Name).Count -eq 0) { $d.PSObject.Properties.Remove('mcpServers') }
  }
  if ($d.PSObject.Properties['hooks'] -and $d.hooks.PSObject.Properties['BeforeTool']) {
    $bt = $d.hooks.BeforeTool
    if ($bt -is [array]) {
      $nb = @()
      foreach ($g in $bt) {
        $kept = @($g.hooks | Where-Object { $_.name -ne 'bailiwick-guardrail' })
        if ($kept.Count -gt 0) { $g.hooks = $kept; $nb += $g }
      }
      if ($nb.Count -gt 0) { $d.hooks.BeforeTool = $nb } else { $d.hooks.PSObject.Properties.Remove('BeforeTool') }
    }
    if (@($d.hooks.PSObject.Properties.Name).Count -eq 0) { $d.PSObject.Properties.Remove('hooks') }
  }
  [System.IO.File]::WriteAllText($f, (($d | ConvertTo-Json -Depth 20) + "`n"))
  Write-Host "  cleaned: bailiwick entries from $f"
}

# Remove skill symlinks that resolve INTO this clone (leave symlinks pointing elsewhere).
function Remove-BailiwickSymlinks {
  $codexH = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
  $rootFwd = (($BailiwickRoot -replace '\\', '/')).TrimEnd('/')
  foreach ($d in @((Join-Path $HOME '.claude/skills'), (Join-Path $HOME '.claude/agents'), (Join-Path $codexH 'skills'))) {
    if (-not (Test-Path $d)) { continue }
    foreach ($item in (Get-ChildItem -LiteralPath $d -Force -ErrorAction SilentlyContinue)) {
      $tgt = $null
      try { $tgt = (Get-Item -LiteralPath $item.FullName -Force).Target } catch { }
      if (-not $tgt) { continue }
      if ((([string]$tgt -replace '\\', '/') -like "$rootFwd*")) {
        if (Dry) { Plan "remove skill symlink $($item.FullName)" }
        else { Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue; Write-Host "  removed symlink: $($item.FullName)" }
      }
    }
  }
  # Generated multi-tool stage adapters (ADR-010 Amendment 1) — remove only files carrying the marker.
  foreach ($d in @((Join-Path $HOME '.gemini/agents'), (Join-Path $codexH 'agents'), (Join-Path $HOME '.copilot/agents'))) {
    if (-not (Test-Path $d)) { continue }
    foreach ($item in (Get-ChildItem -Path $d -Filter 'bailiwick-*' -File -ErrorAction SilentlyContinue)) {
      $c = Get-Content -Path $item.FullName -Raw -ErrorAction SilentlyContinue
      if (-not $c -or ($c -notlike "*GENERATED by bailiwick*")) { continue }
      if (Dry) { Plan "remove generated stage adapter $($item.FullName)" }
      else { Remove-Item -LiteralPath $item.FullName -Force -ErrorAction SilentlyContinue; Write-Host "  removed: generated stage adapter $($item.FullName)" }
    }
  }
}

function Remove-ClaudeUserMcp {
  if (-not (Get-Command claude -ErrorAction SilentlyContinue)) { return }
  foreach ($n in @('bailiwick-filesystem', 'bailiwick-fetch', 'bailiwick-terraform', 'bailiwick-github')) {
    if (Dry) { Plan "claude mcp remove --scope user $n" }
    else { & claude mcp remove $n --scope user *> $null; if ($LASTEXITCODE -eq 0) { Write-Host "  removed: user MCP $n" } }
  }
}

function Remove-Allowlist([string]$bwHome) {
  $f = Join-Path $bwHome 'allowlist'
  if (-not (Test-Path $f)) { return }
  if (Dry) { Plan "remove the shadow allowlist $f (deactivates every shadow repo)" }
  else { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue; Write-Host "  removed: shadow allowlist $f" }
}

# Resolve where Claude Desktop / ChatGPT Desktop keep their own MCP config, if at all. Both apps share
# the same `mcpServers` JSON shape but live OUTSIDE the four sanctioned adapters (no hook system) -
# best-effort path detection for the optional -WithDesktop reference wiring, never a dependency of
# anything else. Sets $script:ClaudeDesktopCfg / $script:ChatgptDesktopCfg (empty if undetectable) and
# $script:DesktopOsNote.
function Resolve-DesktopPaths {
  $script:ClaudeDesktopCfg = ''; $script:ChatgptDesktopCfg = ''; $script:DesktopOsNote = ''
  # $IsWindows is undefined on Windows PowerShell 5.1 (which only ever runs on Windows) - treat null as Windows.
  if ($IsWindows -or ($null -eq $IsWindows)) {
    if ($env:APPDATA) {
      $script:ClaudeDesktopCfg  = Join-Path $env:APPDATA 'Claude/claude_desktop_config.json'
      $script:ChatgptDesktopCfg = Join-Path $env:APPDATA 'ChatGPT/chatgpt_config.json'
    } else {
      $script:DesktopOsNote = 'Windows but %APPDATA% is unset - wire manually'
    }
  } elseif ($IsMacOS) {
    $script:ClaudeDesktopCfg  = Join-Path $HOME 'Library/Application Support/Claude/claude_desktop_config.json'
    $script:ChatgptDesktopCfg = Join-Path $HOME 'Library/Application Support/ChatGPT/chatgpt_config.json'
  } elseif ($IsLinux) {
    # Neither app ships an official Linux build; Claude Desktop community builds follow XDG - best-effort only.
    $script:ClaudeDesktopCfg = Join-Path $HOME '.config/Claude/claude_desktop_config.json'
    $script:DesktopOsNote = 'native Linux - ChatGPT Desktop has no Linux build; the Claude Desktop path is a best-effort guess for unofficial/community builds'
  } else {
    $script:DesktopOsNote = 'unrecognized OS - wire manually'
  }
}

# Drop only the bailiwick-knowledge MCP entry (everything else preserved). Native JSON so uninstall
# needs no python. Best-effort; leaves the file untouched on parse failure.
function Remove-DesktopMcp([string]$f) {
  if (-not $f -or -not (Test-Path -LiteralPath $f)) { return }
  if (-not (Select-String -Path $f -Pattern 'bailiwick-knowledge' -Quiet)) { return }
  if (Dry) { Plan "remove the bailiwick-knowledge MCP entry from $f"; return }
  try { $d = [System.IO.File]::ReadAllText($f) | ConvertFrom-Json } catch { return }
  if ($d.PSObject.Properties['mcpServers']) {
    $d.mcpServers.PSObject.Properties.Remove('bailiwick-knowledge')
    if (@($d.mcpServers.PSObject.Properties.Name).Count -eq 0) { $d.PSObject.Properties.Remove('mcpServers') }
  }
  [System.IO.File]::WriteAllText($f, (($d | ConvertTo-Json -Depth 20) + "`n"))
  Write-Host "  removed: bailiwick-knowledge MCP entry from $f"
}

function Invoke-BailiwickUninstall {
  $codexHomeU  = if ($env:CODEX_HOME)  { $env:CODEX_HOME }  else { Join-Path $HOME '.codex' }
  $geminiHomeU = if ($env:GEMINI_HOME) { $env:GEMINI_HOME } else { Join-Path $HOME '.gemini' }
  $bwHomeU     = if ($env:BAILIWICK_HOME) { $env:BAILIWICK_HOME } else { Join-Path $HOME '.bailiwick' }
  Write-Host ""
  if (Dry) { Write-Host "> bailiwick -Uninstall (DRY RUN - nothing will be changed)" }
  else { Write-Host "> bailiwick -Uninstall - removing global wiring (bailiwick-scoped; a coexisting framework is never touched)" }
  Write-Host "  clone: $BailiwickRoot"
  Remove-ClaudeHooks
  Remove-ClaudeUserMcp
  Remove-MarkerBlock (Join-Path $codexHomeU 'config.toml') '# BEGIN bailiwick hooks' '# END bailiwick hooks' 'Codex guardrail hook'
  Remove-MarkerBlock (Join-Path $codexHomeU 'config.toml') '# BEGIN bailiwick mcp'   '# END bailiwick mcp'   'Codex MCP'
  Remove-MarkerBlock (Join-Path $codexHomeU 'AGENTS.md')   '<!-- BEGIN bailiwick'     '<!-- END bailiwick -->' 'Codex operator layer'
  Remove-MarkerBlock (Join-Path $geminiHomeU 'GEMINI.md')  '<!-- BEGIN bailiwick'     '<!-- END bailiwick -->' 'Gemini operator layer'
  Remove-GeminiJson (Join-Path $geminiHomeU 'settings.json')
  Remove-BailiwickSymlinks
  Resolve-DesktopPaths
  Remove-DesktopMcp $script:ClaudeDesktopCfg
  Remove-DesktopMcp $script:ChatgptDesktopCfg
  Remove-Allowlist $bwHomeU
  Write-Host ""
  Write-Host "  Left intact by design: this clone (delete the directory to remove it fully); your captures,"
  Write-Host "  health shards, and guardrail-audit.log under $bwHomeU (your data); the go-installed"
  Write-Host "  terraform-mcp-server / github-mcp-server binaries; and any per-repo seeded files"
  Write-Host "  (un-seed a repo with '-Uninstall <repo>')."
  if (Dry) { Write-Host "  (dry run - re-run without -DryRun to apply.)" }
}

# ---- per-repo un-seed (reverse SEEDED wiring in one target repo) -------------------------------
# Safe + bailiwick-scoped: removes a seeded file only when it is UNTRACKED *and* carries this clone's
# path; strips only the framework's own .git/info/exclude block; removes just this repo's allowlist
# line; and PRESERVES uncurated captures (delete them explicitly with -PurgeCaptures).
function Remove-SeededFile([string]$abs, [string]$rel, [string]$fingerprint) {
  $f = Join-Path $abs $rel
  if (-not (Test-Path -LiteralPath $f)) { return }
  & git -C $abs ls-files --error-unmatch $rel *> $null
  if ($LASTEXITCODE -eq 0) { Write-Host "  keep (tracked by repo - not ours to remove): $rel"; return }
  if ($fingerprint) {
    $raw = [System.IO.File]::ReadAllText($f)
    $fwd = ($fingerprint -replace '\\', '/')
    if (-not ($raw.Contains($fingerprint) -or (($raw -replace '\\', '/').Contains($fwd)))) {
      Write-Host "  keep (untracked, no bailiwick fingerprint - left as-is): $rel"; return
    }
  }
  if (Dry) { Plan "remove seeded $rel" }
  else { Remove-Item -LiteralPath $f -Force -ErrorAction SilentlyContinue; Write-Host "  removed: $rel" }
}

function Clear-RepoExclude([string]$abs, [bool]$keepCaptureRule = $false) {
  # --git-common-dir, NOT --git-dir: in a linked worktree the latter returns .git/worktrees/<name>,
  # but git reads info/exclude from the COMMON dir.
  $gitdir = (git -C $abs rev-parse --git-common-dir 2>$null)
  if (-not $gitdir) { $gitdir = '.git' }
  if (-not [System.IO.Path]::IsPathRooted($gitdir)) { $gitdir = Join-Path $abs $gitdir }
  $excl = Join-Path $gitdir 'info/exclude'
  if (-not (Test-Path -LiteralPath $excl)) { return }
  $cur = [System.IO.File]::ReadAllText($excl)
  if (-not $cur.Contains('bailiwick framework wiring')) { return }
  if (Dry) { Plan "strip the framework block from $excl (your own exclude rules preserved)"; return }
  $ours = @('.mcp.json', '.vscode/mcp.json', 'CLAUDE.local.md',
            '.bailiwick.local.md', '.codex/config.toml', '.gemini/settings.json',
            '.github/instructions/bailiwick.instructions.md')
  # When captures survive the uninstall, their ignore rule must survive with them — otherwise the
  # next `git add -A` stages plaintext session transcripts (mirror of bootstrap.sh
  # strip_repo_exclude; the keep-note string must stay byte-identical across both scripts).
  if (-not $keepCaptureRule) { $ours += '.bailiwick-outputs/' }
  $keepNote = "# bailiwick: kept $([char]0x2014) uncurated plaintext captures still present (see --purge-captures)"
  $out = @()
  foreach ($ln in ($cur -split "\r?\n")) {
    $s = $ln.Trim()
    if ($s.Contains('bailiwick framework wiring')) { continue }
    if ($ours -contains $s) { continue }
    if ($s -eq $keepNote) { continue }
    $out += $ln
  }
  if ($keepCaptureRule) {
    $idx = [array]::IndexOf(($out | ForEach-Object { $_.Trim() }), '.bailiwick-outputs/')
    if ($idx -eq 0) { $out = @($keepNote) + $out }
    elseif ($idx -gt 0) { $out = @($out[0..($idx-1)]) + $keepNote + @($out[$idx..($out.Count-1)]) }
  }
  $text = ($out -join "`n").TrimEnd()   # drop any trailing blank the block left behind
  if ($text.Length -gt 0) { $text += "`n" }
  [System.IO.File]::WriteAllText($excl, $text)
  Write-Host "  removed: framework block from $excl (your own exclude rules preserved)"
}

function Remove-AllowlistEntry([string]$abs, [string]$bwHome) {
  $f = Join-Path $bwHome 'allowlist'
  if (-not (Test-Path -LiteralPath $f)) { return }
  $lines = [System.IO.File]::ReadAllText($f) -split "\r?\n"
  if (-not (@($lines | Where-Object { $_.Trim() -eq $abs }).Count)) { return }
  if (Dry) { Plan "remove this repo's allowlist entry ($abs)"; return }
  $kept = @($lines | Where-Object { $_.Trim() -ne $abs })
  $text = ($kept -join "`n").TrimEnd()   # drop the trailing empty the split may have produced
  if ($text.Length -gt 0) { $text += "`n" }
  [System.IO.File]::WriteAllText($f, $text)
  Write-Host "  removed: this repo's shadow-allowlist entry"
}

function Show-RepoCaptures([string]$abs) {
  # Returns $true when .bailiwick-outputs/ SURVIVES (its ignore rule must be kept) — mirror of
  # bootstrap.sh warn_repo_captures.
  $out = Join-Path $abs '.bailiwick-outputs'
  if (-not (Test-Path -LiteralPath $out)) { return $false }
  if ($PurgeCaptures) {
    if (Dry) { Plan "delete $out INCLUDING any captures (-PurgeCaptures)"; return $false }
    Remove-Item -LiteralPath $out -Recurse -Force -ErrorAction SilentlyContinue
    Write-Host "  removed: .bailiwick-outputs/ (-PurgeCaptures - captures deleted)"
    return $false
  }
  $rawDir = Join-Path $out 'raw'
  $n = 0
  if (Test-Path -LiteralPath $rawDir) {
    $n = @(Get-ChildItem -LiteralPath $rawDir -Recurse -File -ErrorAction SilentlyContinue |
      Where-Object { ($_.Extension -eq '.jsonl' -or $_.Extension -eq '.md') -and ($_.FullName -notmatch '[\\/]\.curated[\\/]') }).Count
  }
  if ($n -gt 0) {
    Write-Host "  PRESERVED: .bailiwick-outputs/ holds ~$n uncurated capture file(s) - left in place,"
    Write-Host "             and its .git/info/exclude rule is KEPT so they stay untracked. These are"
    Write-Host "             PLAINTEXT session transcripts: do not commit them."
    Write-Host "             Promote them with /curate, or delete via: -Uninstall -PurgeCaptures '$abs'"
  } else {
    Write-Host "  note: .bailiwick-outputs/ left in place (no uncurated captures); its exclude rule is kept"
    Write-Host "        while the directory exists - remove both by hand if unwanted."
  }
  return $true
}

function Invoke-BailiwickRepoUninstall([string]$repo) {
  if (-not (Test-Path -LiteralPath $repo -PathType Container)) { Write-Error "not a directory: $repo"; return }
  $abs = Get-NativePath ((Resolve-Path -LiteralPath $repo).Path)
  $bwHomeU = if ($env:BAILIWICK_HOME) { $env:BAILIWICK_HOME } else { Join-Path $HOME '.bailiwick' }
  Write-Host ""
  if (Dry) { Write-Host "> bailiwick -Uninstall '$abs' (DRY RUN - nothing will be changed)" }
  else { Write-Host "> bailiwick -Uninstall '$abs' - removing per-repo seeded wiring" }
  Write-Host "  (tracked team files, -WithStandards baselines, and captures are preserved)"
  Remove-SeededFile $abs 'CLAUDE.local.md' $BailiwickRoot
  Remove-SeededFile $abs '.bailiwick.local.md' ''
  Remove-SeededFile $abs '.mcp.json' $BailiwickRoot
  Remove-SeededFile $abs '.vscode/mcp.json' $BailiwickRoot
  Remove-SeededFile $abs '.codex/config.toml' $BailiwickRoot
  Remove-SeededFile $abs '.gemini/settings.json' $BailiwickRoot
  Remove-SeededFile $abs '.github/instructions/bailiwick.instructions.md' ''
  if (-not (Dry)) {
    foreach ($d in @('.vscode', '.codex', '.github/instructions', '.github')) {
      $dp = Join-Path $abs $d
      if ((Test-Path -LiteralPath $dp) -and (-not (Get-ChildItem -LiteralPath $dp -Force -ErrorAction SilentlyContinue))) {
        Remove-Item -LiteralPath $dp -Force -ErrorAction SilentlyContinue
      }
    }
  }
  # Captures FIRST: uninstalling must never un-hide plaintext transcripts it deliberately
  # preserves — when they survive, their exclude rule survives with them (mirror of bootstrap.sh
  # uninstall_repo; this ordering is the 8e750b8 capture-leak fix).
  $keepCaptureRule = [bool](Show-RepoCaptures $abs)
  Clear-RepoExclude $abs $keepCaptureRule
  Remove-AllowlistEntry $abs $bwHomeU
  Write-Host ""
  Write-Host "  This only un-wires the repo. The once-per-machine GLOBAL wiring (hooks, operator layers,"
  Write-Host "  skills, user MCP) stays - remove that with '-Uninstall' (no target). The clone and your"
  Write-Host "  ~/.bailiwick/ data remain."
  if (Dry) { Write-Host "  (dry run - re-run without -DryRun to apply.)" }
}

# -InstallTools with NO target = global-only: install/validate the once-per-machine prerequisites
# --- github MCP auth resolution -------------------------------------------------
# The github MCP server needs an API token for the account that owns the FRAMEWORK
# (this Bailiwick's own git remote) — NOT necessarily gh's *active* account, which on a
# company-managed laptop is usually the company identity and cannot see your personal
# repos. Derive the owner from the framework remote, find a logged-in gh account that can
# actually reach it, and pin the MCP server to THAT account's token via
# `gh auth token --user` (resolved lazily at spawn from gh's keychain — never persisted
# to a dotfile or the environment, and survives `gh auth switch`). Falls back to the
# ${GITHUB_TOKEN} env var when gh can't provide a usable token (CI / token-only, or the
# personal account isn't logged into gh yet).
# Wrapped as a function so BOTH paths use it: the shadow block (global bailiwick-github MCP) and the
# seeded path (per-repo github MCP). Publishes: $script:ghUser/ghHost/ghDecided/ghWarn.
function Resolve-GhAccount {
  $ghUser = ''; $ghHost = ''; $ghOwnerRepo = ''; $ghRealHost = ''; $ghAlias = ''
  $bailiwickRemote = (git -C $BailiwickRoot remote get-url origin 2>$null)
  if ((-not $NoGhAuth) -and $bailiwickRemote) {
    $u = $bailiwickRemote -replace '\.git$', ''
    if ($u -match '://') {
      $hp = ($u -replace '^[^:]+://', '') -replace '^[^@]+@', ''
      $ghAlias = ($hp -split '/')[0]
      $ghOwnerRepo = ($hp -replace '^[^/]+/', '')
    } elseif ($u -match '@[^:]+:') {
      $rest = ($u -replace '^[^@]+@', '')
      $ghAlias = ($rest -split ':')[0]
      $ghOwnerRepo = ($rest -replace '^[^:]+:', '')
    }
    if ($ghAlias) {
      $hn = (ssh -G $ghAlias 2>$null | Select-String '^hostname ' | Select-Object -First 1)
      if ($hn) { $ghRealHost = (($hn.Line -split '\s+')[1]) }
    }
    if ($ghRealHost -notmatch '\.') { $ghRealHost = 'github.com' }
  }
  # Account selection (priority): (1) explicit override in $BailiwickRoot\.bailiwick-sync.json
  # (github_account + optional github_host); (2) owner->account map (github_account_map) — the
  # deterministic, machine-readable form of the gitconfig rewrite-rule intent (gitconfig maps an
  # owner to an SSH *alias*, not a gh *login*, so the bridge is declared here); (3) the access probe,
  # which collects ALL accounts that can read the repo: exactly one wins silently; more than one is
  # AMBIGUOUS — default to the active account, warn, and point at github_account_map. Disambiguation
  # only bites on multi-account machines (client laptops / VMs).
  $ghOwner = ($ghOwnerRepo -split '/')[0]; $ghDecided = ''; $ghWarn = ''
  $cfgPath = Join-Path $BailiwickRoot '.bailiwick-sync.json'
  $cfg = $null
  if (Test-Path -LiteralPath $cfgPath) { try { $cfg = (Get-Content -Raw -LiteralPath $cfgPath | ConvertFrom-Json) } catch { $cfg = $null } }
  if ((Get-Command gh -ErrorAction SilentlyContinue) -and $ghOwnerRepo) {
    $ovrAcct = if ($cfg) { [string]$cfg.github_account } else { '' }
    $ovrHost = if ($cfg) { [string]$cfg.github_host } else { '' }
    $mapAcct = ''
    if ($cfg -and $cfg.github_account_map) { $mapAcct = [string]$cfg.github_account_map.$ghOwner }
    $pick = ''; $pickHost = $ghRealHost
    if ($ovrAcct) { $pick = $ovrAcct; if ($ovrHost) { $pickHost = $ovrHost }; $ghDecided = 'override' }
    elseif ($mapAcct) { $pick = $mapAcct; $ghDecided = 'account-map' }
    if ($pick) {
      # Honour the declared choice — it only needs a usable token (no access probe).
      $tok = (gh auth token --hostname $pickHost --user $pick 2>$null)
      if ($tok) { $ghUser = $pick; $ghHost = $pickHost }
      else { $ghWarn = "configured gh account '$pick' has no token on $pickHost (run 'gh auth login' for it) - fell back to the access probe"; $ghDecided = '' }
    }
    if (-not $ghUser) {
      # Access probe — collect EVERY account that can read the repo, not just the first.
      $cands = @()
      foreach ($line in (gh auth status 2>$null)) {
        $toks = ($line -split '\s+')
        for ($i = 0; $i -lt $toks.Count; $i++) { if ($toks[$i] -eq 'account') { $cands += $toks[$i + 1] } }
      }
      $activeTok = (gh auth token --hostname $ghRealHost 2>$null)
      $readers = @(); $activeMatch = ''
      foreach ($acct in $cands) {
        $tok = (gh auth token --hostname $ghRealHost --user $acct 2>$null)
        if (-not $tok) { continue }
        $env:GH_TOKEN = $tok
        gh api --hostname $ghRealHost "repos/$ghOwnerRepo" *> $null
        $ok = ($LASTEXITCODE -eq 0)
        Remove-Item Env:GH_TOKEN -ErrorAction SilentlyContinue
        if ($ok) { $readers += $acct; if ($activeTok -and ($tok -eq $activeTok)) { $activeMatch = $acct } }
      }
      if ($readers.Count -eq 1) { $ghUser = $readers[0]; $ghHost = $ghRealHost; $ghDecided = 'probe' }
      elseif ($readers.Count -gt 1) {
        $ghUser = if ($activeMatch) { $activeMatch } else { $readers[0] }
        $ghHost = $ghRealHost; $ghDecided = 'ambiguous'
        $aliasShown = if ($ghAlias) { $ghAlias } else { 'n/a' }
        $ghWarn = "multiple gh accounts can read $ghOwnerRepo ($($readers -join ', ')) - defaulted to '$ghUser' (remote uses SSH profile '$aliasShown'). Pin it deterministically by adding to ${cfgPath}: `"github_account_map`": { `"$ghOwner`": `"<account>`" }"
      }
    }
  }
  $script:ghUser = $ghUser; $script:ghHost = $ghHost
  $script:ghDecided = $ghDecided; $script:ghWarn = $ghWarn
  # The seeded-path status messages read these too — without publishing them the account-map
  # message printed an empty key and the "no account can reach <repo>" diagnostic never fired.
  $script:ghOwner = $ghOwner; $script:ghOwnerRepo = $ghOwnerRepo; $script:ghRealHost = $ghRealHost
}

# and skip ALL per-repo wiring. Shadow mode makes this global-first setup the norm.

# ADR-009: mirror of hooks/public_origin.sh. Warn (never fatal) when this clone's origin is the
# public OSS repo or any public GitHub fork of it — developing/validating here is legitimate,
# ingesting knowledge is not. Override: "allow_public_push": true in .bailiwick-sync.json.
$script:CanonicalSlug = 'Cursorinvisivel/bailiwick'
function Get-OriginSlug([string]$root) {
  $url = (git -C $root remote get-url origin 2>$null)
  if (-not $url) { return '' }
  $url = $url -replace '\.git$', '' -replace '/$', ''
  $parts = $url -split '[/:]' | Where-Object { $_ -ne '' }
  if ($parts.Count -lt 2) { return '' }
  return "$($parts[-2])/$($parts[-1])"
}
function Test-PublicOrigin([string]$root) {
  $slug = Get-OriginSlug $root
  if (-not $slug) { return $null }
  $cfg = Join-Path $root '.bailiwick-sync.json'
  if (Test-Path -LiteralPath $cfg) {
    try {
      if ((Get-Content -Raw -LiteralPath $cfg | ConvertFrom-Json).allow_public_push -eq $true) { return $null }
    } catch { }
  }
  if ($slug.ToLower() -eq $script:CanonicalSlug.ToLower()) { return "origin is the public OSS repo ($slug)" }
  if (Get-Command gh -ErrorAction SilentlyContinue) {
    $private = (gh api "repos/$slug" --jq '.private' 2>$null)
    if ($private -eq 'false') { return "origin ($slug) is a PUBLIC GitHub repository" }
  }
  return $null
}
function Warn-PublicOrigin {
  $root = Split-Path -Parent $PSScriptRoot
  $reason = Test-PublicOrigin $root
  if ($reason) {
    Write-Host ""
    Write-Host "  WARNING (ADR-009): $reason."
    Write-Host "  This clone is CONTRIBUTE-ONLY: develop and validate freely, but /curate will not promote"
    Write-Host "  and sync_knowledge.sh will refuse to push - knowledge/ is tracked, so it would publish."
    Write-Host "  For your own instance, point 'origin' at a private repo you own (docs/staying-private.md)."
    Write-Host ""
  }
}

$GlobalOnly = ($InstallTools -and -not $Target)
if ($Help -or (-not $Target -and -not $GlobalOnly -and -not $Uninstall)) {
  Get-Help $PSCommandPath -Detailed 2>$null
  Write-Host "Usage: bootstrap.ps1 [-Seeded|-Shadow] [-Init] [-WithAgents] [-WithCopilot] [-AllTools] [-WithStandards] [-Update] [-Visible] [-Force] [-Clobber] [-NoGhAuth] [-InstallTools] [-WithDesktop] [-DryRun] <target-repo-path>"
  Write-Host "       bootstrap.ps1 -InstallTools [-WithDesktop]   (global-only: no target repo needed)"
  Write-Host "       bootstrap.ps1 -Uninstall [-DryRun]     (remove the global once-per-machine wiring; bailiwick-scoped)"
  Write-Host "       bootstrap.ps1 -Uninstall <repo> [-PurgeCaptures] [-DryRun]  (un-seed one repo; captures preserved)"
  Write-Host "Default mode is SHADOW (zero-footprint; personal): no files are written into the repo."
  Write-Host "-DryRun previews every change and writes nothing. -Uninstall reverses global wiring (no target) or un-seeds a repo (with target)."
  if (-not $Target -and -not $GlobalOnly) { exit 2 } else { exit 0 }
}
if ($AllTools) { $WithAgents = $true; $WithCopilot = $true; $WithGemini = $true }

# Mode resolution — SHADOW is the DEFAULT (zero-footprint; personal). -Seeded selects the in-repo
# hidden wiring; -Visible and -Init imply seeded (they write repo files by design). -Shadow stays
# accepted as an explicit alias for the default.
if ($Shadow -and ($Seeded -or $Visible -or $Init)) {
  Write-Error "-Shadow conflicts with -Seeded/-Visible/-Init (those write repo files by design; shadow writes none)"; exit 2
}
if ($Seeded -or $Visible -or $Init) { $Seeded = $true; $Shadow = $false } else { $Shadow = $true }

# -Clobber is the destructive reset; it is inert unless paired with -Force (intentionality gate).
if ($Clobber -and -not $Force) {
  Write-Error "-Clobber requires -Force (the two-flag combo is the intentionality gate for a destructive reset)"; exit 2
}

# -Uninstall reverses framework wiring and exits. With a target repo it un-seeds THAT repo;
# with no target it reverses the once-per-machine global wiring.
if ($Uninstall) {
  if ($Target) { Invoke-BailiwickRepoUninstall $Target } else { Invoke-BailiwickUninstall }
  exit 0
}

if ($DryRun) { Write-Host "> bailiwick -DryRun - previewing changes; nothing will be written." }

if ($GlobalOnly) { Write-Host "* bailiwick : $BailiwickRoot (global-only install - no target repo)" }

# ===== per-repo wiring — skipped entirely in global-only mode (matching brace before the
# once-per-machine prerequisites section) =====
if (-not $GlobalOnly) {

# A '-'/'--'-prefixed value in the target position is almost always a mistyped switch (PowerShell uses
# SINGLE-dash switches, not the bash '--dry-run' style). Catch it with a clear message instead of the
# confusing "target does not exist" — and before -Init could create a directory named after the flag.
if ($Target -like '-*') {
  Write-Error ("'$Target' looks like a flag, not a repo path. PowerShell uses single-dash switches " +
    "(e.g. -DryRun, -Seeded, -Uninstall) — not the bash-style --dry-run. Pass a target repo path, " +
    "or use -InstallTools / -Uninstall for the no-target modes.")
  exit 2
}

if (-not (Test-Path $Target)) {
  if ($Init) {
    # -DryRun must not create the directory either — resolve $Target textually below.
    if (Dry) { Plan "mkdir $Target" } else { New-Item -ItemType Directory -Force -Path $Target | Out-Null }
  }
  else { Write-Error "target '$Target' does not exist (use -Init to create it)"; exit 2 }
}
if (Test-Path $Target) {
  $Target = Get-NativePath ((Resolve-Path -LiteralPath $Target).Path)
} elseif (-not [System.IO.Path]::IsPathRooted($Target)) {  # dry-run -Init on a not-yet-existing dir
  $Target = Get-NativePath (Join-Path (Get-Location).Path $Target)
}
$RepoName = Split-Path $Target -Leaf

if (-not (Test-Path (Join-Path $Target '.git'))) {
  if ($Init) {
    if (Dry) { Plan "git init $Target" } else { git -C $Target init -q; Write-Host "* git init: $Target" }
  }
  else { Write-Error "'$Target' is not a git repo (use -Init to create one)"; exit 2 }
}

Write-Host "* bailiwick : $BailiwickRoot"
Write-Host "* target  : $Target ($RepoName)"
if ($Clobber) {
  Write-Host "! CLOBBER+FORCE: tracked complement files and existing baseline standards WILL be overwritten."
  Write-Host "  Tracked files are recoverable via 'git checkout -- <file>'; untracked overwrites are not."
}

# JSON path values use forward slashes (valid JSON + accepted on Windows).
$tkJson = $BailiwickRoot -replace '\\', '/'
$tgJson = $Target  -replace '\\', '/'

# True if a path is already tracked by the target repo. Tracked files are PROJECT-OWNED:
# .git/info/exclude cannot hide them and seeding would clobber project content — so never touch them.
function Test-Tracked([string]$rel) {
  git -C $Target ls-files --error-unmatch $rel *> $null
  return ($LASTEXITCODE -eq 0)
}

function Write-Managed([string]$rel, [string]$content) {   # generated config — refreshed on -Update/-Force
  if (Dry) { Plan "write managed config $rel"; return }
  $dest = Join-Path $Target $rel
  if ((Test-Path $dest) -and -not $Force -and -not $Update) { Write-Host "  skip (exists): $rel"; return }
  $existed = Test-Path $dest
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  [System.IO.File]::WriteAllText($dest, $content)   # UTF-8, no BOM
  if ($existed) { Write-Host "  updated: $rel" } else { Write-Host "  wrote: $rel" }
}

function Copy-Seeded([string]$src, [string]$rel) {        # seeded once, then hand-edited — never auto-clobbered
  if (Dry) { Plan "seed complement file $rel"; return }
  $dest = Join-Path $Target $rel
  if (Test-Tracked $rel) {
    if ($Clobber) {
      # Destructive reset explicitly requested (-Clobber -Force): overwrite the project-owned file.
      # It stays tracked & visible; recover with 'git checkout -- <file>' if unintended.
      $txt = (Get-Content -Raw -LiteralPath $src).Replace($CanonPath, $BailiwickRoot).Replace('[Project / Repo Name]', $RepoName)
      [System.IO.File]::WriteAllText($dest, $txt); Write-Host "  CLOBBERED (tracked file overwritten — recover via git): $rel"; return
    }
    # Project owns this file — never seed/overwrite (even -Force) and never pretend to hide it.
    Write-Host "  skip (tracked by repo — left untouched; can't be hidden, won't clobber): $rel"; return
  }
  if (Test-Path $dest) {
    if ($Force) {
      $txt = (Get-Content -Raw -LiteralPath $src).Replace($CanonPath, $BailiwickRoot).Replace('[Project / Repo Name]', $RepoName)
      [System.IO.File]::WriteAllText($dest, $txt); Write-Host "  overwrote: $rel"; return
    }
    $cur = Get-Content -Raw -LiteralPath $dest
    if (($CanonPath -ne $BailiwickRoot) -and $cur.Contains($CanonPath)) {
      [System.IO.File]::WriteAllText($dest, $cur.Replace($CanonPath, $BailiwickRoot)); Write-Host "  path-fixed: $rel"
    } else { Write-Host "  keep (edited): $rel" }
    return
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  $txt = (Get-Content -Raw -LiteralPath $src).Replace($CanonPath, $BailiwickRoot).Replace('[Project / Repo Name]', $RepoName)
  [System.IO.File]::WriteAllText($dest, $txt); Write-Host "  wrote: $rel"
}

function Copy-Standard([string]$src, [string]$rel) {     # agnostic baseline, TRACKED (shared) — preserved unless -Clobber -Force
  $dest = Join-Path $Target $rel
  $existed = Test-Path $dest
  if ($existed -and -not $Clobber) { Write-Host "  keep (exists, not overwritten): $rel"; return }
  if (Dry) {  # tracked, SHARED files — the highest-blast-radius writes this script makes
    if ($existed) { Plan "CLOBBER tracked baseline $rel (reset to template)" } else { Plan "write tracked baseline $rel" }
    return
  }
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  $txt = (Get-Content -Raw -LiteralPath $src).Replace('[Project / Repo Name]', $RepoName)
  [System.IO.File]::WriteAllText($dest, $txt)
  if ($existed) { Write-Host "  CLOBBERED (baseline reset — recover via git): $rel" } else { Write-Host "  wrote (tracked baseline): $rel" }
}

# Canonical "Working intelligence" reuse block, read live from the template (single source of truth):
# the section header through the line *before* "- **Read before you write.**". The header's em-dash
# is built via [char]0x2014 so Windows PowerShell 5.1 (which may read this BOM-less file as ANSI)
# still matches the UTF-8 template exactly; file reads go through [System.IO.File] (UTF-8).
$StdSectionHdr = '## Working intelligence ' + [char]0x2014 + ' before writing anything'
function Get-ReuseBlock([string]$path) {                 # returns the canonical block from a baseline file
  $out = New-Object System.Collections.Generic.List[string]
  $inBlock = $false
  foreach ($l in [System.IO.File]::ReadAllLines($path)) {
    if ($l -ceq $StdSectionHdr) { $inBlock = $true }
    if ($inBlock -and ($l -cmatch '^- \*\*Read before you write\.\*\*')) { break }
    if ($inBlock) { $out.Add($l) }
  }
  return ($out -join "`n")
}
function Update-StandardSection([string]$rel, [string]$canonBlock) {  # patch ONLY the reuse section, in place
  $dest = Join-Path $Target $rel
  if (-not (Test-Path $dest)) { return }
  $lines = @([System.IO.File]::ReadAllLines($dest))
  if (-not ($lines -ccontains $StdSectionHdr)) {
    Write-Host "  note: no '$StdSectionHdr' section in $rel - left untouched (hand-edited?)"; return
  }
  if (@($lines | Where-Object { $_ -cmatch '^- \*\*Read before you write\.\*\*' }).Count -eq 0) {
    Write-Host "  note: reuse-section end anchor missing in $rel - left untouched"; return
  }
  # Idempotency: skip when the target's section already matches the canonical block.
  if ((Get-ReuseBlock $dest) -ceq $canonBlock) { Write-Host "  reuse rule already current: $rel"; return }
  if (Dry) { Plan "refresh the reuse section in $rel (tracked file)"; return }
  $blockLines = $canonBlock -split "`n"
  $out = New-Object System.Collections.Generic.List[string]
  $inSection = $false
  foreach ($l in $lines) {
    if ($l -ceq $StdSectionHdr) { $inSection = $true; foreach ($b in $blockLines) { $out.Add($b) }; continue }
    if ($inSection -and ($l -cmatch '^- \*\*Read before you write\.\*\*')) { $inSection = $false }
    if (-not $inSection) { $out.Add($l) }
  }
  [System.IO.File]::WriteAllText($dest, (($out -join "`n") + "`n"))
  Write-Host "  refreshed reuse rule: $rel (prior version recoverable via git)"
}

# --- agnostic baseline STANDARD files (TRACKED/shared, no framework refs) — only with -WithStandards ---
# Seeded only when absent (an existing team file is never overwritten) and NOT added to .git/info/exclude:
# these are meant to be committed and shared. Runs in BOTH modes — in (default) shadow mode they are
# the ONLY files written into the repo (no hidden complements, no exclude entries for them).
function Invoke-SeedStandards {
  $std = Join-Path $BailiwickRoot 'knowledge/templates/agnostic-standards-baseline.md'
  if ($Update) {
    # Non-destructive refresh: patch ONLY the reuse-rule section of an EXISTING committed baseline,
    # leaving the rest of the team's hand-edited file intact. Seeds nothing new; touches whichever of
    # the three baseline files already exist. Recover a prior section via git if needed.
    $canon = Get-ReuseBlock $std
    foreach ($f in @('CLAUDE.md', 'AGENTS.md', '.github/copilot-instructions.md')) { Update-StandardSection $f $canon }
  } else {
    Copy-Standard $std 'CLAUDE.md'
    if ($WithAgents)  { Copy-Standard $std 'AGENTS.md' }
    if ($WithCopilot) { Copy-Standard $std '.github/copilot-instructions.md' }
  }
}

# --- federation: enabled external read-only roots from the framework registry ---
# Added as MCP filesystem roots so the Federation Agent can CONSULT them (read-only is a
# policy rule — see agents/federation.md). No-op while none enabled.
$extRoots = @()
$srcReg = Join-Path $BailiwickRoot '.bailiwick-sources.json'
if (Test-Path $srcReg) {
  try {
    $reg = Get-Content -Raw -LiteralPath $srcReg | ConvertFrom-Json
    foreach ($s in $reg.sources) {
      if ($s.enabled -and (($s.kind -eq 'filesystem') -or (-not $s.kind)) -and $s.location) {
        $extRoots += ($s.location -replace '\\', '/')
      }
    }
  } catch { }
}
$mcpRoots = '"' + $tgJson + '", "' + $tkJson + '"'
$vscRoots = '"${workspaceFolder}", "' + $tkJson + '"'
foreach ($r in $extRoots) { $mcpRoots += ', "' + $r + '"'; $vscRoots += ', "' + $r + '"' }
if ($extRoots.Count -gt 0) { Write-Host "  federation: $($extRoots.Count) external read-only root(s) wired into MCP" }

# --- Shadow mode (FRAMEWORK.md 7.1, the DEFAULT): activate globally, write NOTHING into the ------
# repo (except the TRACKED -WithStandards baselines, which are the deliberate shared path).
# Bypasses ALL repo-file seeding / MCP-file / .git-exclude logic below.
if ($Shadow) {
  $bwHomeS = if ($env:BAILIWICK_HOME) { $env:BAILIWICK_HOME } else { Join-Path $HOME '.bailiwick' }
  $allowFile = Join-Path $bwHomeS 'allowlist'

  # 1. Allowlist entry (idempotent) — the gate (hooks + tool layers) activates on this.
  # Guarded: adding the entry ACTIVATES the framework for the repo, which is exactly the kind of
  # state change -DryRun promises not to make.
  $allowLines = if (Test-Path $allowFile) { @([System.IO.File]::ReadAllLines($allowFile)) } else { @() }
  if ($allowLines -ccontains $Target) {
    Write-Host "  allowlist: already present - $Target"
  } elseif (Dry) {
    Plan "add $Target to $allowFile (shadow activation)"
  } else {
    New-Item -ItemType Directory -Force -Path $bwHomeS | Out-Null
    if (-not (Test-Path $allowFile)) {
      $allowHdr = "# bailiwick shadow allowlist - one absolute repo root per line (# comments).`n" +
                  "# Listed repos activate the framework with NO files written into them (FRAMEWORK.md 7.1).`n"
      [System.IO.File]::WriteAllText($allowFile, $allowHdr)
    }
    Add-Content -LiteralPath $allowFile -Value $Target
    Write-Host "  allowlist: added - $Target"
  }

  # 2. Global user-scope MCP for Claude Code (filesystem root = Bailiwick + federation; the working
  #    repo is read natively). Applies to all repos; activation stays gated by the allowlist above.
  $shRoots = @($tkJson) + $extRoots
  # Account-aware github MCP for the GLOBAL scope: resolve the account that owns the framework
  # (override > account-map > access probe - same rules as the per-repo flow) and build the
  # lazy spawn-time token wrapper. Empty ghUser (no gh, probe failed, -NoGhAuth) => skipped.
  Resolve-GhAccount
  $ghShadowSh = ''
  if ($script:ghUser) {
    $ghShadowSh = "GITHUB_PERSONAL_ACCESS_TOKEN=`$(gh auth token --hostname $($script:ghHost) --user $($script:ghUser)) exec github-mcp-server stdio"
    Write-Host "  gh: global bailiwick-github pinned to '$($script:ghUser)' on $($script:ghHost) ($($script:ghDecided))"
    if ($script:ghWarn) { Write-Host "  ! gh: $($script:ghWarn)" }
  }
  if (Get-Command claude -ErrorAction SilentlyContinue) {
    $script:mcpUserList = ((claude mcp list 2>$null) -join "`n")
    function Register-UserMcp([string]$name, [string[]]$spawn) {   # idempotent, non-fatal
      if (Dry) { Plan "register user MCP '$name' (claude mcp add --scope user)"; return }
      if ($script:mcpUserList -match ('(?m)(^|\s)' + [regex]::Escape($name) + '(\s|:|$)')) {
        Write-Host "  mcp(user): $name already registered"; return
      }
      & claude mcp add --scope user $name -- @spawn *> $null
      if ($LASTEXITCODE -eq 0) { Write-Host "  mcp(user): registered $name" }
      else { Write-Host "  mcp(user): could not register $name - add manually: claude mcp add --scope user $name -- $($spawn -join ' ')" }
    }
    Register-UserMcp 'bailiwick-filesystem' (@('npx', '-y', '@modelcontextprotocol/server-filesystem') + $shRoots)
    Register-UserMcp 'bailiwick-fetch' @('uvx', '--with', 'mcp<2', 'mcp-server-fetch')
    Register-UserMcp 'bailiwick-terraform' @('terraform-mcp-server', 'stdio')
    if ($ghShadowSh) { Register-UserMcp 'bailiwick-github' @('sh', '-c', $ghShadowSh) }
    else { Write-Host "  mcp(user): bailiwick-github not registered (no usable gh account - see gh notes) - add manually if wanted" }
  } else {
    Write-Host "  X 'claude' CLI not found - register the framework MCP root manually:"
    Write-Host "      claude mcp add --scope user bailiwick-filesystem -- npx -y @modelcontextprotocol/server-filesystem `"$tkJson`""
  }

  # Optional GLOBAL MCP for Codex / Gemini, opted in per tool via -WithAgents / -WithGemini.
  # Uses bailiwick-* server names (never collides with your own) and github is omitted (per-repo token).
  if ($WithGemini) {
    $gemHome = if ($env:GEMINI_HOME) { $env:GEMINI_HOME } else { Join-Path $HOME '.gemini' }
    $gemFile = Join-Path $gemHome 'settings.json'
    if (Dry) { Plan "merge bailiwick-* MCP servers into $gemFile" } else {
    New-Item -ItemType Directory -Force -Path $gemHome | Out-Null
    try {
      $gem = $null
      if ((Test-Path $gemFile) -and ((Get-Item -LiteralPath $gemFile).Length -gt 0)) {
        try { $gem = ([System.IO.File]::ReadAllText($gemFile) | ConvertFrom-Json) } catch { $gem = $null }
      }
      if (-not $gem) { $gem = New-Object psobject }
      if (-not $gem.PSObject.Properties['mcpServers']) {
        $gem | Add-Member -NotePropertyName 'mcpServers' -NotePropertyValue (New-Object psobject)
      }
      $srv = $gem.mcpServers
      $srv | Add-Member -Force -NotePropertyName 'bailiwick-filesystem' -NotePropertyValue ([pscustomobject]@{
        command = 'npx'; args = @('-y', '@modelcontextprotocol/server-filesystem') + $shRoots })
      $srv | Add-Member -Force -NotePropertyName 'bailiwick-fetch' -NotePropertyValue ([pscustomobject]@{
        command = 'uvx'; args = @('--with', 'mcp<2', 'mcp-server-fetch') })
      $srv | Add-Member -Force -NotePropertyName 'bailiwick-terraform' -NotePropertyValue ([pscustomobject]@{
        command = 'terraform-mcp-server'; args = @('stdio') })
      if ($ghShadowSh) {
        $srv | Add-Member -Force -NotePropertyName 'bailiwick-github' -NotePropertyValue ([pscustomobject]@{
          command = 'sh'; args = @('-c', $ghShadowSh) })
      }
      [System.IO.File]::WriteAllText($gemFile, (($gem | ConvertTo-Json -Depth 10) + "`n"))
      Write-Host "  mcp(gemini): merged bailiwick-* servers into $gemFile"
    } catch {
      Write-Host "  mcp(gemini): could not update $gemFile - edit by hand"
    }
    }
  }
  if ($WithAgents) {
    $codexHomeShadow = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME '.codex' }
    $codexCfg = Join-Path $codexHomeShadow 'config.toml'
    if (Dry) { Plan "inject the bailiwick-* MCP block into $codexCfg" } else {
    New-Item -ItemType Directory -Force -Path $codexHomeShadow | Out-Null
    $fsExtra = ''
    foreach ($r in $shRoots) { $fsExtra += ', "' + $r + '"' }
    $tomlBlock = "# BEGIN bailiwick mcp (managed - refreshed by bootstrap.ps1 -WithAgents in shadow mode)`n" +
                 "[mcp_servers.bailiwick-filesystem]`ncommand = `"npx`"`n" +
                 "args = [`"-y`", `"@modelcontextprotocol/server-filesystem`"$fsExtra]`n" +
                 "[mcp_servers.bailiwick-fetch]`ncommand = `"uvx`"`nargs = [`"--with`", `"mcp<2`", `"mcp-server-fetch`"]`n" +
                 "[mcp_servers.bailiwick-terraform]`ncommand = `"terraform-mcp-server`"`nargs = [`"stdio`"]`n" +
                 $(if ($ghShadowSh) { "[mcp_servers.bailiwick-github]`ncommand = `"sh`"`nargs = [`"-c`", `"$ghShadowSh`"]`n" } else { '' }) +
                 "# END bailiwick mcp"
    if ((Test-Path $codexCfg) -and (Select-String -LiteralPath $codexCfg -Pattern '# BEGIN bailiwick mcp' -SimpleMatch -Quiet)) {
      $cur = [System.IO.File]::ReadAllText($codexCfg)
      # MatchEvaluator (not a replacement string) so literal '$' in the block is never treated as a
      # regex substitution; Singleline so '.' spans the multi-line managed block.
      $tomlEval = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $tomlBlock }
      $new = [System.Text.RegularExpressions.Regex]::Replace(
        $cur, '# BEGIN bailiwick mcp.*?# END bailiwick mcp', $tomlEval,
        [System.Text.RegularExpressions.RegexOptions]::Singleline)
      [System.IO.File]::WriteAllText($codexCfg, $new)
      Write-Host "  mcp(codex): refreshed bailiwick-* block in $codexCfg"
    } else {
      $sep = if ((Test-Path $codexCfg) -and ((Get-Item -LiteralPath $codexCfg).Length -gt 0)) { "`n" } else { '' }
      Add-Content -LiteralPath $codexCfg -Value ($sep + $tomlBlock)
      Write-Host "  mcp(codex): added bailiwick-* block to $codexCfg"
    }
    }
  }
  if ($WithCopilot) { Write-Host "  mcp(copilot): user-scope MCP is set via VS Code -> 'MCP: Open User Configuration' (not scriptable here)" }

  # -WithStandards works in shadow mode too: the baselines are TRACKED team files, seeded
  # deliberately and shared — so no hidden complements and no exclude entries are added for them.
  if ($WithStandards) {
    Write-Host "  standards: seeding TRACKED team baselines (-WithStandards; shadow adds no hidden wiring)"
    Invoke-SeedStandards
  }

  Write-Host ""
  if ($WithStandards) {
    Write-Host "OK Shadow-wired '$RepoName' - no hidden wiring written (only the TRACKED -WithStandards baselines above)."
  } else {
    Write-Host "OK Shadow-wired '$RepoName' - NO files written into the repo (repo tree untouched)."
  }
  Write-Host "This repo is opted in via the allowlist; activation is otherwise global."
  Write-Host "Next:"
  Write-Host "  - Claude Code : hooks must be installed once globally - run 'bootstrap.ps1 -InstallTools' (global-only,"
  Write-Host "      no target needed; or merge settings.template.json). SessionStart now activates on the"
  Write-Host "      allowlist; captures stage centrally under $bwHomeS\captures\<repo>\ - the repo stays clean."
  Write-Host "  - Codex/Gemini: install/refresh the global operator layers (-InstallTools) - they now activate on"
  Write-Host "      ~/.bailiwick/allowlist (or BAILIWICK_SHADOW=1), no marker needed, and read the framework by"
  Write-Host "      path natively. Global fetch/terraform MCP servers are injected by -WithAgents / -WithGemini"
  Write-Host "      (above); github stays manual (per-repo token)."
  Write-Host "  - Copilot (VS Code): user-scope MCP via 'MCP: Open User Configuration'; user instructions are"
  Write-Host "      build-dependent (VS Code #304101). See FRAMEWORK.md 7.1."
  Write-Host "  - one-off (any tool): set BAILIWICK_SHADOW=1 to force-activate the current shell."
  # -InstallTools alongside a shadow run: continue to the once-per-machine global install below
  # (the seeded per-repo wiring stays skipped — shadow writes no wiring files into the repo).
  if (-not $InstallTools) { exit 0 }
  Write-Host "  -InstallTools: continuing to the global prerequisites install..."
}

# ===== seeded-mode wiring — skipped entirely in shadow mode (matching brace after exclude pruning) =====
if (-not $Shadow) {

# github MCP account resolution — see Resolve-GhAccount above the shadow block.
Resolve-GhAccount
$ghUser = $script:ghUser; $ghHost = $script:ghHost; $ghDecided = $script:ghDecided; $ghWarn = $script:ghWarn
if ($ghUser) {
  $ghSh = "GITHUB_PERSONAL_ACCESS_TOKEN=`$(gh auth token --hostname $ghHost --user $ghUser) exec github-mcp-server stdio"
  $ghBlockMcp = '"command": "sh",' + "`n      " + '"args": ["-c", "' + $ghSh + '"]'
  $ghBlockVsc = $ghBlockMcp
  # Codex config.toml form (TOML): reuse the same spawn-time gh-auth command.
  $ghBlockToml = 'command = "sh"' + "`n" + 'args = ["-c", "' + $ghSh + '"]'
  $via = switch ($ghDecided) {
    'override'    { ' via .bailiwick-sync.json github_account' }
    'account-map' { " via .bailiwick-sync.json github_account_map[$ghOwner]" }
    'ambiguous'   { ' via access probe (AMBIGUOUS - see warning)' }
    default       { '' }
  }
  $ghStatusMsg = "github MCP -> gh account '$ghUser' on $ghHost$via (token resolved at spawn; no env var needed)"
} else {
  $ghBlockMcp = '"command": "github-mcp-server",' + "`n      " + '"args": ["stdio"],' + "`n      " + '"env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${GITHUB_TOKEN}" }'
  $ghBlockVsc = '"command": "github-mcp-server",' + "`n      " + '"args": ["stdio"],' + "`n      " + '"env": { "GITHUB_PERSONAL_ACCESS_TOKEN": "${env:GITHUB_TOKEN}" }'
  # Codex form maps GITHUB_TOKEN via a spawn shell (robust regardless of Codex env expansion).
  $ghBlockToml = 'command = "sh"' + "`n" + 'args = ["-c", "GITHUB_PERSONAL_ACCESS_TOKEN=${GITHUB_TOKEN} exec github-mcp-server stdio"]'
  if ($NoGhAuth) {
    $ghStatusMsg = "set GITHUB_TOKEN with a personal PAT (gh probe skipped via -NoGhAuth)"
  } elseif ((Get-Command gh -ErrorAction SilentlyContinue) -and $ghOwnerRepo) {
    $ghStatusMsg = "no logged-in gh account can reach $ghOwnerRepo on $ghRealHost - run 'gh auth login' for that account, or set GITHUB_TOKEN with a personal PAT"
  } else {
    $ghStatusMsg = "set GITHUB_TOKEN with a personal PAT (gh CLI not detected, or no Bailiwick remote to derive the account)"
  }
}
Write-Host "  $ghStatusMsg"
if ($ghWarn) { Write-Host "  WARNING: $ghWarn" }

# --- .mcp.json (Claude Code) — backtick escapes keep `${...} literal; $mcpRoots is prebuilt literal ---
Write-Managed '.mcp.json' @"
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", $mcpRoots]
    },
    "fetch": {
      "command": "uvx",
      "args": ["--with", "mcp<2", "mcp-server-fetch"]
    },
    "github": {
      $ghBlockMcp
    },
    "terraform": {
      "command": "terraform-mcp-server",
      "args": ["stdio"]
    }
  }
}
"@

# --- .vscode/mcp.json (VS Code) ---
Write-Managed '.vscode/mcp.json' @"
{
  "servers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", $vscRoots]
    },
    "fetch": {
      "command": "uvx",
      "args": ["--with", "mcp<2", "mcp-server-fetch"]
    },
    "github": {
      $ghBlockVsc
    },
    "terraform": {
      "command": "terraform-mcp-server",
      "args": ["stdio"]
    }
  }
}
"@

# --- framework guidance as HIDDEN COMPLEMENT files (never the team's shared standard files) ---
# Each tool loads its complement alongside (not replacing) any team file; all are gitignored below
# and still load (filesystem discovery). Per-tool adapter:
#   Claude Code : CLAUDE.local.md  (native personal memory; merges after CLAUDE.md)
#   Codex       : .bailiwick.local.md  (private marker read via the global ~/.codex/AGENTS.md
#                 layer; a neutral marker, so it never shadows the team AGENTS.md)
#   Copilot     : .github/instructions/bailiwick.instructions.md  (local VS Code only)
Copy-Seeded (Join-Path $BailiwickRoot 'knowledge/templates/project-claude-md-template.md') 'CLAUDE.local.md'
# On -Update, refresh whatever complement/config already exists (detect per tool).
$seedMarker = $false; $geminiGenerated = $false
if ($Update -and (Test-Path (Join-Path $Target '.bailiwick.local.md')))                                  { $seedMarker = $true }
if ($Update -and (Test-Path (Join-Path $Target '.codex/config.toml')))                                   { $WithAgents = $true }
if ($Update -and (Test-Path (Join-Path $Target '.gemini/settings.json')) -and (-not (Test-Tracked '.gemini/settings.json'))) { $WithGemini = $true }
if ($Update -and (Test-Path (Join-Path $Target '.github/instructions/bailiwick.instructions.md')))    { $WithCopilot = $true }

# Shared private marker — read by BOTH Codex (~/.codex/AGENTS.md) and Gemini (~/.gemini/GEMINI.md).
if ($WithAgents -or $WithGemini -or $seedMarker) {
  Copy-Seeded (Join-Path $BailiwickRoot 'knowledge/templates/project-agents-md-template.md') '.bailiwick.local.md'
}
if ($WithAgents)  {
  # Codex MCP lives in config.toml (NOT .mcp.json). Current Codex CLI loads user-scope
  # ~/.codex/config.toml for MCP; this repo-local file is retained as a generated draft/reference
  # until Codex supports project-local config loading in this environment. Shadow mode injects the
  # working user-scope bailiwick-* MCP block into ~/.codex/config.toml.
  Write-Managed '.codex/config.toml' @"
# bailiwick — Codex MCP servers (repo-local draft/reference). Managed: regenerated on -Update/-Force.
# Current Codex CLI loads MCP from ~/.codex/config.toml, not this project-local file.
# Use bootstrap.ps1 -WithAgents (shadow mode, the default) for working user-scope Codex MCP injection.

[mcp_servers.filesystem]
command = "npx"
args = ["-y", "@modelcontextprotocol/server-filesystem", $mcpRoots]

[mcp_servers.fetch]
command = "uvx"
args = ["--with", "mcp<2", "mcp-server-fetch"]

[mcp_servers.github]
$ghBlockToml

[mcp_servers.terraform]
command = "terraform-mcp-server"
args = ["stdio"]
"@
}
if ($WithGemini) {
  # Gemini MCP lives in .gemini/settings.json (one file for Gemini CLI + Code Assist VS Code agent).
  # Google documents it as committable/shared, so a TEAM-TRACKED settings.json is LEFT UNTOUCHED.
  # excludeTools is ADVISORY ONLY (Google: "simple string matching", "not a security mechanism").
  if (Test-Tracked '.gemini/settings.json') {
    Write-Host "  skip (tracked by repo — left untouched; merge framework MCP by hand): .gemini/settings.json"
  } else {
    Write-Managed '.gemini/settings.json' @"
{
  "mcpServers": {
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", $mcpRoots]
    },
    "fetch": {
      "command": "uvx",
      "args": ["--with", "mcp<2", "mcp-server-fetch"]
    },
    "github": {
      $ghBlockMcp
    },
    "terraform": {
      "command": "terraform-mcp-server",
      "args": ["stdio"]
    }
  },
  "excludeTools": [
    "run_shell_command(terraform apply)",
    "run_shell_command(terraform destroy)",
    "run_shell_command(terragrunt apply)",
    "run_shell_command(terragrunt destroy)"
  ]
}
"@
    $geminiGenerated = $true
  }
}
if ($WithCopilot) { Copy-Seeded (Join-Path $BailiwickRoot 'knowledge/templates/copilot-bailiwick-instructions-template.md') '.github/instructions/bailiwick.instructions.md' }

# --- agnostic baseline STANDARD files (TRACKED/shared) — see Invoke-SeedStandards above. They coexist
# with the hidden complements in seeded mode (and are the only repo writes in shadow mode).
if ($WithStandards) { Invoke-SeedStandards }

# --- capture staging ---
if (Dry) { Plan "create capture staging .bailiwick-outputs/raw/" } else { New-Item -ItemType Directory -Force -Path (Join-Path $Target '.bailiwick-outputs/raw') | Out-Null }

# --- hide locally via .git/info/exclude (never the tracked .gitignore) ---
# --git-common-dir, NOT --git-dir: git resolves info/exclude from the common dir, so in a linked
# worktree the rules would be written where git never reads them, leaving captures git-visible.
$gitDir = (git -C $Target rev-parse --git-common-dir 2>$null)
if (-not $gitDir) { $gitDir = '.git' }
if (-not [System.IO.Path]::IsPathRooted($gitDir)) { $gitDir = Join-Path $Target $gitDir }
$exclude = Join-Path $gitDir 'info/exclude'
if (-not (Dry)) {
  New-Item -ItemType Directory -Force -Path (Split-Path $exclude) | Out-Null
  if (-not (Test-Path $exclude)) { New-Item -ItemType File -Force -Path $exclude | Out-Null }
}
$existing = @(Get-Content -LiteralPath $exclude -ErrorAction SilentlyContinue)
$mark = '# bailiwick framework wiring (local-only - never shared)'
function Add-Excl([string]$p) {
  if (Dry) { Plan "exclude $p via .git/info/exclude"; return }
  if (Test-Tracked $p) { Write-Host "  note: '$p' is tracked by the repo — left visible (exclude cannot hide a tracked file)"; return }
  if ($script:existing -notcontains $p) { Add-Content -LiteralPath $exclude -Value $p; $script:existing += $p }
}
if ((-not (Dry)) -and ($existing -notcontains $mark)) { Add-Content -LiteralPath $exclude -Value "`n$mark"; $existing += $mark }
Add-Excl '.bailiwick-outputs/'
if (-not $Visible) {
  Add-Excl '.mcp.json'; Add-Excl '.vscode/mcp.json'; Add-Excl 'CLAUDE.local.md'
  if ($WithAgents -or $WithGemini) { Add-Excl '.bailiwick.local.md' }
  if ($WithAgents)     { Add-Excl '.codex/config.toml' }
  if ($geminiGenerated){ Add-Excl '.gemini/settings.json' }
  if ($WithCopilot) { Add-Excl '.github/instructions/bailiwick.instructions.md' }
  Write-Host "  hidden: framework files excluded via .git/info/exclude (not shared)"
} else {
  Write-Host "  visible: framework files left tracked (.bailiwick-outputs/ still local-only)"
}

}  # ===== end seeded-mode wiring (shadow mode with -InstallTools resumes here) =====

}  # ===== end per-repo wiring (global-only mode resumes here) =====

# ADR-009: surface a contribute-only origin before the prerequisites report, not buried under it.
if ($InstallTools) { Warn-PublicOrigin }

# --- validate (and with -InstallTools, install) the once-per-machine prerequisites ---
# Under -DryRun, describe what -InstallTools would mutate globally, then neutralize it so the status
# block below reports CURRENT state without touching anything.
if ($DryRun -and $InstallTools) {
  Write-Host ""
  Write-Host "  [dry-run] -InstallTools would, when a piece is missing:"
  Write-Host "    - go install terraform-mcp-server + github-mcp-server (needs 'go')"
  Write-Host "    - merge capture + guardrail hooks into ~/.claude/settings.json (install_hooks.py)"
  Write-Host "    - wire the guardrail into ~/.codex/config.toml + ~/.gemini/settings.json (install_adapter_hooks.py)"
  Write-Host "    - symlink skills into ~/.claude/skills/ and ~/.codex/skills/"
  Write-Host "    - symlink Quality Workflow stages into ~/.claude/agents/ (native subagents, ADR-010)"
  Write-Host "    - generate multi-tool stage adapters: ~/.gemini/agents/, ~/.codex/agents/ (TOML), ~/.copilot/agents/"
  Write-Host "    - install operator layers into ~/.codex/AGENTS.md + ~/.gemini/GEMINI.md"
  if ($WithDesktop) { Write-Host "    - wire the knowledge-scoped bailiwick-knowledge MCP into Claude/ChatGPT Desktop configs (install_desktop_mcp.py)" }
  Write-Host "  [dry-run] nothing installed; the status lines below reflect the CURRENT state."
  $InstallTools = $false
}
# terraform MCP server is wired into .mcp.json on EVERY run (not just -AllTools).
if ((-not (Get-Command terraform-mcp-server -ErrorAction SilentlyContinue)) -and $InstallTools -and (Get-Command go -ErrorAction SilentlyContinue)) {
  Write-Host "  -InstallTools: installing terraform-mcp-server (go install)..."
  & go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@latest 2>&1 | ForEach-Object { "    $_" }
  $gobin = (& go env GOPATH 2>$null)
  if ($gobin) { $env:PATH = "$gobin/bin" + [IO.Path]::PathSeparator + $env:PATH }
}
if (Get-Command terraform-mcp-server -ErrorAction SilentlyContinue) {
  $tfStatus = "OK terraform-mcp-server on PATH ($((Get-Command terraform-mcp-server).Source))"
} elseif (Get-Command go -ErrorAction SilentlyContinue) {
  $tfStatus = "MISSING terraform-mcp-server - run: go install github.com/hashicorp/terraform-mcp-server/cmd/terraform-mcp-server@latest  (or re-run with -InstallTools; then add `$(go env GOPATH)\bin to PATH)"
} else {
  $tfStatus = "MISSING terraform-mcp-server and 'go' not found - install Go, then re-run with -InstallTools (see README)"
}

# fetch MCP server runs via uvx (Astral). Unlike the two Go servers there is no binary to install -
# uvx fetches mcp-server-fetch on demand - so the ONLY prerequisite is uv itself. Without it the
# server is still registered and fails at connect time with a bare "ENOENT", which points at nothing.
$uvBin = Join-Path $HOME '.local\bin'
if ((-not (Get-Command uvx -ErrorAction SilentlyContinue)) -and $InstallTools) {
  Write-Host "  -InstallTools: installing uv (Astral installer -> $uvBin)..."
  try { Invoke-RestMethod https://astral.sh/uv/install.ps1 | Invoke-Expression } catch { Write-Host "    uv install failed: $_" }
  if (Test-Path (Join-Path $uvBin 'uvx.exe')) { $env:PATH = $uvBin + [IO.Path]::PathSeparator + $env:PATH }
}
if (Get-Command uvx -ErrorAction SilentlyContinue) {
  $uvStatus = "OK uvx on PATH ($((Get-Command uvx).Source)) - bailiwick-fetch can start"
} elseif (Test-Path (Join-Path $uvBin 'uvx.exe')) {
  $uvStatus = "MISSING uv installed to $uvBin - add that dir to PATH (bailiwick-fetch fails with ENOENT until you do)"
} else {
  $uvStatus = "MISSING uvx - bailiwick-fetch will fail to connect with 'ENOENT'. Run: irm https://astral.sh/uv/install.ps1 | iex  (or re-run with -InstallTools; then ensure $uvBin is on PATH)"
}

# github MCP server is GitHub's official local Go binary (stdio), wired the same Docker-free way.
if ((-not (Get-Command github-mcp-server -ErrorAction SilentlyContinue)) -and $InstallTools -and (Get-Command go -ErrorAction SilentlyContinue)) {
  Write-Host "  -InstallTools: installing github-mcp-server (go install)..."
  & go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest 2>&1 | ForEach-Object { "    $_" }
  $gobin = (& go env GOPATH 2>$null)
  if ($gobin) { $env:PATH = "$gobin/bin" + [IO.Path]::PathSeparator + $env:PATH }
}
if (Get-Command github-mcp-server -ErrorAction SilentlyContinue) {
  $ghMcpStatus = "OK github-mcp-server on PATH ($((Get-Command github-mcp-server).Source))"
} elseif (Get-Command go -ErrorAction SilentlyContinue) {
  $ghMcpStatus = "MISSING github-mcp-server - run: go install github.com/github/github-mcp-server/cmd/github-mcp-server@latest  (or re-run with -InstallTools; then add `$(go env GOPATH)\bin to PATH)"
} else {
  $ghMcpStatus = "MISSING github-mcp-server and 'go' not found - install Go, then re-run with -InstallTools (see README)"
}

# capture/curation hooks are installed once-globally; detect/merge in ~/.claude/settings.json.
$userSettings = Join-Path $HOME ".claude/settings.json"
$hookTmpl = Join-Path $BailiwickRoot "hooks/settings.template.json"
# Scoped to THIS clone's path, not the bare filename: a hook left behind by another clone (a
# renamed/retired predecessor) also contains "capture_session.py", and matching that made
# -InstallTools skip the merge and report OK while the OLD clone's code stayed live (doctor.sh's
# "hooks execute a DIFFERENT clone"). install_hooks.py migrates such an install to here.
function Test-HooksPresent {
  if (-not (Test-Path $userSettings)) { return $false }
  # Separators vary (JSON-escaped '\\', native '\', or '/' left by the template rewrite) — collapse
  # every run of backslashes to '/' on both sides so the comparison is about the PATH, not its spelling.
  $needle = ((Join-Path $BailiwickRoot "hooks/capture_session.py") -replace '\\+', '/').ToLower()
  $text = ((Get-Content -Raw -Path $userSettings) -replace '\\+', '/').ToLower()
  return $text.Contains($needle)
}
# Windows PowerShell 5.1 has no '??' null-coalescing operator — use a plain fallback.
$pyExe = Get-Command python3 -ErrorAction SilentlyContinue
if (-not $pyExe) { $pyExe = Get-Command python -ErrorAction SilentlyContinue }
if ((-not (Test-HooksPresent)) -and $InstallTools -and $pyExe -and (Test-Path $hookTmpl)) {
  Write-Host "  -InstallTools: merging capture/curation hooks into ~/.claude/settings.json..."
  & $pyExe.Source (Join-Path $BailiwickRoot "hooks/install_hooks.py") $userSettings $hookTmpl 2>&1 | ForEach-Object { "    $_" }
}
# Codex + Gemini hook adapters: the guardrail (same engine as the Claude Code guardrail; deny/ask
# contract per tool) everywhere, plus Codex capture on Stop/SessionEnd (codex-cli >= 0.147, the
# same scripts Claude Code runs). All self-gating to wired/shadow repos - see
# hooks/install_adapter_hooks.py.
if ($InstallTools -and $pyExe) {
  Write-Host "  -InstallTools: wiring Codex hooks (guardrail PreToolUse + capture Stop/SessionEnd) and the Gemini guardrail (BeforeTool)..."
  & $pyExe.Source (Join-Path $BailiwickRoot "hooks/install_adapter_hooks.py") 2>&1 | ForEach-Object { "    $_" }
}
if (Test-HooksPresent) {
  $hooksStatus = "OK capture/curation hooks present in ~/.claude/settings.json"
} elseif (Test-Path $userSettings) {
  $hooksStatus = "MISSING bailiwick hooks in ~/.claude/settings.json - merge the 'hooks' block from `$BAILIWICK\hooks\settings.template.json (or re-run with -InstallTools)"
} else {
  $hooksStatus = "MISSING ~/.claude/settings.json - install hooks once: merge from `$BAILIWICK\hooks\settings.template.json (or re-run with -InstallTools)"
}

# Skills are GLOBAL (once per machine), like the hooks — symlink every skill dir under
# skills/ into ~/.claude/skills/ (curate, enrich, ...).
$skillsDir = Join-Path $BailiwickRoot "skills"
$skillMissing = 0; $skillTotal = 0
foreach ($skillDir in (Get-ChildItem -Path $skillsDir -Directory -ErrorAction SilentlyContinue)) {
  $skillTotal++
  $skillLink = Join-Path $HOME ".claude/skills/$($skillDir.Name)"
  if ((-not (Test-Path $skillLink)) -and $InstallTools) {
    Write-Host "  -InstallTools: linking /$($skillDir.Name) skill globally (~/.claude/skills/$($skillDir.Name))..."
    New-Item -ItemType Directory -Force -Path (Split-Path $skillLink) | Out-Null
    New-Item -ItemType SymbolicLink -Path $skillLink -Target $skillDir.FullName -ErrorAction SilentlyContinue | Out-Null
  }
  if (-not (Test-Path $skillLink)) { $skillMissing++ }
}
if ($skillMissing -eq 0 -and $skillTotal -gt 0) {
  $skillStatus = "OK $skillTotal skill(s) linked globally (~/.claude/skills/: curate, enrich, ...)"
} else {
  $skillStatus = "MISSING $skillMissing/$skillTotal skills - re-run with -InstallTools, or symlink each dir under `$BAILIWICK/skills/ into ~/.claude/skills/"
}

# Quality Workflow stages as NATIVE Claude Code subagents (ADR-010) - GLOBAL, like the skills:
# every agents/*.md carrying `name:` frontmatter (the 7 stages) is symlinked into
# ~/.claude/agents/<name>.md. lead.md (the orchestrator = the main session) and the 5 domain
# context files have no frontmatter and are deliberately NOT installed. Never seeded per-repo.
$agentsSrcDir = Join-Path $BailiwickRoot "agents"
$stageMissing = 0; $stageTotal = 0
foreach ($agentFile in (Get-ChildItem -Path $agentsSrcDir -Filter *.md -File -ErrorAction SilentlyContinue)) {
  $head = Get-Content -Path $agentFile.FullName -TotalCount 20 -ErrorAction SilentlyContinue
  if (-not $head -or $head[0] -ne '---') { continue }
  $stageName = $null
  foreach ($line in $head[1..($head.Count-1)]) {
    if ($line -eq '---') { break }
    if ($line -match '^name:\s*(.+)$') { $stageName = $Matches[1].Trim(); break }
  }
  if (-not $stageName) { continue }
  $stageTotal++
  $stageLink = Join-Path $HOME ".claude/agents/$stageName.md"
  if ((-not (Test-Path $stageLink)) -and $InstallTools) {
    Write-Host "  -InstallTools: linking $stageName stage as a native subagent (~/.claude/agents/$stageName.md)..."
    New-Item -ItemType Directory -Force -Path (Split-Path $stageLink) | Out-Null
    New-Item -ItemType SymbolicLink -Path $stageLink -Target $agentFile.FullName -ErrorAction SilentlyContinue | Out-Null
  }
  if (-not (Test-Path $stageLink)) { $stageMissing++ }
}
if ($stageMissing -eq 0 -and $stageTotal -gt 0) {
  $agentStageStatus = "OK $stageTotal Quality Workflow stage(s) linked as native subagents (~/.claude/agents/: bailiwick-implement, bailiwick-quality, ...)"
} else {
  $agentStageStatus = "MISSING $stageMissing/$stageTotal stages not linked as subagents - re-run with -InstallTools, or symlink each frontmattered `$BAILIWICK/agents/*.md into ~/.claude/agents/<name>.md"
}

# Multi-tool stage adapters (ADR-010 Amendment 1): GENERATED user-scope agent definitions for
# Gemini (~/.gemini/agents/<name>.md), Codex (~/.codex/agents/<name>.toml) and Copilot
# (~/.copilot/agents/<name>.agent.md) from the canonical frontmattered agents/*.md. The
# Claude-specific tools: field is dropped; a toolset without Edit/Write maps to Codex
# sandbox_mode = "read-only". Regenerated each -InstallTools; files without the GENERATED
# marker are never overwritten.
$mtMark = "GENERATED by bailiwick"
$mtGen = 0; $mtSkip = 0
$codexHomeForAgents = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
if ($InstallTools) {
  foreach ($agentFile in (Get-ChildItem -Path $agentsSrcDir -Filter *.md -File -ErrorAction SilentlyContinue)) {
    $raw = Get-Content -Path $agentFile.FullName -Raw
    if ($raw -notmatch '(?s)^---\r?\n(.*?)\r?\n---\r?\n(.*)$') { continue }
    $fm = $Matches[1]; $stBody = $Matches[2]
    $stName = if ($fm -match '(?m)^name:\s*(.+)$') { $Matches[1].Trim() } else { $null }
    $stDesc = if ($fm -match '(?m)^description:\s*(.+)$') { $Matches[1].Trim() } else { $null }
    $stTools = if ($fm -match '(?m)^tools:\s*(.+)$') { $Matches[1].Trim() } else { "" }
    if (-not $stName -or -not $stDesc) { continue }
    $readOnly = ($stTools -ne "") -and ($stTools -notmatch '\b(Edit|Write)\b')
    $note = "$mtMark from `$BAILIWICK/agents/$($agentFile.Name) -- edit the source and re-run -InstallTools; do not edit here."
    $mdAdapter = "---`n# $note`nname: $stName`ndescription: $stDesc`n---`n$stBody"
    $tomlDesc = $stDesc.Replace('\', '\\').Replace('"', '\"')
    $tomlBody = $stBody.Replace('"""', '\"\"\"')
    $sandboxLine = if ($readOnly) { "sandbox_mode = `"read-only`"`n" } else { "" }
    $tomlAdapter = "# $note`nname = `"$stName`"`ndescription = `"$tomlDesc`"`n$sandboxLine" + "developer_instructions = `"`"`"`n$tomlBody`n`"`"`"`n"
    $outs = @(
      @{ Dest = (Join-Path $HOME ".gemini/agents/$stName.md");            Content = $mdAdapter },
      @{ Dest = (Join-Path $HOME ".copilot/agents/$stName.agent.md");     Content = $mdAdapter },
      @{ Dest = (Join-Path $codexHomeForAgents "agents/$stName.toml");    Content = $tomlAdapter }
    )
    foreach ($o in $outs) {
      New-Item -ItemType Directory -Force -Path (Split-Path $o.Dest) | Out-Null
      if (Test-Path $o.Dest) {
        $old = Get-Content -Path $o.Dest -Raw -ErrorAction SilentlyContinue
        if ($old -and ($old -notlike "*$mtMark*")) { Write-Host "  SKIP (unmanaged file exists, not overwriting): $($o.Dest)"; $mtSkip++; continue }
        if ($old -eq $o.Content) { continue }
      }
      Set-Content -Path $o.Dest -Value $o.Content -NoNewline
      $mtGen++
    }
  }
  Write-Host "  -InstallTools: multi-tool stage adapters - generated/updated $mtGen, skipped $mtSkip"
}
$mtCount = 0
foreach ($d in @((Join-Path $HOME ".gemini/agents"), (Join-Path $codexHomeForAgents "agents"), (Join-Path $HOME ".copilot/agents"))) {
  if (Test-Path $d) { $mtCount += (Get-ChildItem -Path $d -Filter 'bailiwick-*' -File -ErrorAction SilentlyContinue).Count }
}
$mtExpect = $stageTotal * 3
if ($mtCount -ge $mtExpect -and $stageTotal -gt 0) {
  $mtAgentStatus = "OK $mtCount multi-tool stage adapter(s) generated (Gemini ~/.gemini/agents/, Codex ~/.codex/agents/, Copilot ~/.copilot/agents/)"
} elseif ($mtCount -gt 0) {
  $mtAgentStatus = "PARTIAL $mtCount/$mtExpect multi-tool stage adapters present - re-run with -InstallTools to regenerate"
} else {
  $mtAgentStatus = "MISSING multi-tool stage adapters (Gemini/Codex/Copilot) not generated - re-run with -InstallTools"
}

# Codex skills are thin wrappers around the canonical Claude Code skill procedures. They live in
# the framework and are symlinked into ~/.codex/skills so Codex can discover them without copying.
$codexHomeForSkills = if ($env:CODEX_HOME) { $env:CODEX_HOME } else { Join-Path $HOME ".codex" }
$codexSkillsDir = Join-Path $BailiwickRoot "codex-skills"
$codexSkillsHome = Join-Path $codexHomeForSkills "skills"
$codexSkillMissing = 0; $codexSkillTotal = 0
foreach ($skillDir in (Get-ChildItem -Path $codexSkillsDir -Directory -ErrorAction SilentlyContinue)) {
  $codexSkillTotal++
  $skillLink = Join-Path $codexSkillsHome $skillDir.Name
  if ((-not (Test-Path $skillLink)) -and $InstallTools) {
    Write-Host "  -InstallTools: linking `$$($skillDir.Name) Codex skill globally ($skillLink)..."
    New-Item -ItemType Directory -Force -Path (Split-Path $skillLink) | Out-Null
    New-Item -ItemType SymbolicLink -Path $skillLink -Target $skillDir.FullName -ErrorAction SilentlyContinue | Out-Null
  }
  if (-not (Test-Path $skillLink)) { $codexSkillMissing++ }
}
if ($codexSkillTotal -eq 0) {
  $codexSkillStatus = "MISSING no Codex skills found in `$BAILIWICK/codex-skills"
} elseif ($codexSkillMissing -eq 0) {
  $codexSkillStatus = "OK $codexSkillTotal Codex skill(s) linked globally (~/.codex/skills/: bailiwick-curate, bailiwick-enrich, ...)"
} else {
  $codexSkillStatus = "MISSING $codexSkillMissing/$codexSkillTotal Codex skills - re-run with -InstallTools, or symlink each dir under `$BAILIWICK/codex-skills/ into ~/.codex/skills/"
}

# Codex & Gemini private operator layers are GLOBAL (once per machine): a managed block in
# ~/.codex/AGENTS.md and ~/.gemini/GEMINI.md that activates per-repo on the untracked
# .bailiwick.local.md marker. Each loads BEFORE the repo's own file (team file keeps precedence)
# and never shadows it. Merge logic is inline (native PowerShell) so Windows needs no bash; the
# templates are shared with install_global_layer.sh.
function Test-GlobalLayer([string]$dest) { (Test-Path $dest) -and (Select-String -Path $dest -Pattern 'BEGIN bailiwick' -Quiet) }
function Install-GlobalLayer([string]$tmpl, [string]$dest) {
  $block = (Get-Content -Raw -LiteralPath $tmpl).Replace('__BAILIWICK__', ($BailiwickRoot -replace '\\','/'))
  New-Item -ItemType Directory -Force -Path (Split-Path $dest) | Out-Null
  if (Test-GlobalLayer $dest) {
    $cur = Get-Content -Raw -LiteralPath $dest
    # MatchEvaluator (not a replacement string) so literal '$' in the block is not treated as a
    # regex substitution; Singleline so '.' spans the multi-line managed block.
    $evaluator = [System.Text.RegularExpressions.MatchEvaluator]{ param($m) $block.TrimEnd() }
    $new = [System.Text.RegularExpressions.Regex]::Replace(
      $cur, '<!-- BEGIN bailiwick.*?<!-- END bailiwick -->', $evaluator,
      [System.Text.RegularExpressions.RegexOptions]::Singleline)
    [System.IO.File]::WriteAllText($dest, $new)
  } else {
    $sep = if ((Test-Path $dest) -and (Get-Item $dest).Length -gt 0) { "`n" } else { "" }
    Add-Content -LiteralPath $dest -Value ($sep + $block.TrimEnd())
  }
}
$codexHome   = if ($env:CODEX_HOME)  { $env:CODEX_HOME }  else { Join-Path $HOME ".codex" }
$geminiHome  = if ($env:GEMINI_HOME) { $env:GEMINI_HOME } else { Join-Path $HOME ".gemini" }
$codexAgents  = Join-Path $codexHome  "AGENTS.md"
$geminiAgents = Join-Path $geminiHome "GEMINI.md"
$codexTmpl  = Join-Path $BailiwickRoot "hooks/codex-global-agents.tmpl.md"
$geminiTmpl = Join-Path $BailiwickRoot "hooks/gemini-global.tmpl.md"
if ($InstallTools) {
  if (Test-Path $codexTmpl) {
    Write-Host "  -InstallTools: installing/refreshing the Codex operator layer in ~/.codex/AGENTS.md..."
    Install-GlobalLayer $codexTmpl $codexAgents
  }
  if (Test-Path $geminiTmpl) {
    Write-Host "  -InstallTools: installing/refreshing the Gemini operator layer in ~/.gemini/GEMINI.md..."
    Install-GlobalLayer $geminiTmpl $geminiAgents
  }
}
if (Test-GlobalLayer $codexAgents) {
  $codexStatus = "OK Codex operator layer present (~/.codex/AGENTS.md) - activates on .bailiwick.local.md"
} else {
  $codexStatus = "MISSING Codex operator layer - re-run with -InstallTools. Only needed if you use Codex."
}
if ($WithAgents -and (-not $Shadow) -and (-not $GlobalOnly)) {
  $codexMcpStatus = "WARN Codex MCP: .codex/config.toml was generated as a repo-local draft, but current Codex CLI reports MCP from ~/.codex/config.toml only. Run '-WithAgents' in shadow mode (the default, without -Seeded) to inject working user-scope bailiwick-* MCP."
} else {
  $codexMcpStatus = ""
}
if (Test-GlobalLayer $geminiAgents) {
  $geminiStatus = "OK Gemini operator layer present (~/.gemini/GEMINI.md) - activates on .bailiwick.local.md"
} else {
  $geminiStatus = "MISSING Gemini operator layer - re-run with -InstallTools. Only needed if you use Gemini."
}

# --- Optional knowledge-SCOPED reference for Claude Desktop / ChatGPT Desktop (-WithDesktop) ---
# Scoped to knowledge/ only, but the filesystem server is read-WRITE within that root and Desktop
# has no hooks - so it can modify the library outside every gate. Not a read-only channel.
# Neither app has a hook system, so this is deliberately OUTSIDE capture/curation/guardrails (those only
# cover the four sanctioned adapters). A single bailiwick-knowledge MCP filesystem server rooted at
# knowledge/ ONLY, never the rest of the framework. Opt-in and
# -InstallTools-gated; status is always shown once detection runs (mirrors bootstrap.sh --with-desktop).
$desktopInstr = Join-Path $BailiwickRoot 'knowledge/templates/desktop-reference-instructions.md'
Resolve-DesktopPaths
function Test-DesktopWired([string]$f) { $f -and (Test-Path -LiteralPath $f) -and (Select-String -Path $f -Pattern 'bailiwick-knowledge' -Quiet) }
function Invoke-DesktopWire([string]$label, [string]$cfg) {
  if (-not $cfg) { return }
  Write-Host "  -WithDesktop: $label knowledge reference ($cfg)..."
  & $pyExe.Source (Join-Path $BailiwickRoot 'hooks/install_desktop_mcp.py') $cfg (Join-Path $BailiwickRoot 'knowledge') 2>&1 | ForEach-Object { "    $_" }
}
if ($WithDesktop -and $InstallTools -and $pyExe) {
  Write-Host "  -WithDesktop: wiring the knowledge-scoped reference MCP server (read-write within knowledge/)..."
  Invoke-DesktopWire 'Claude Desktop' $script:ClaudeDesktopCfg
  Invoke-DesktopWire 'ChatGPT Desktop' $script:ChatgptDesktopCfg
} elseif ($WithDesktop -and $InstallTools -and -not $pyExe) {
  Write-Host "  -WithDesktop: SKIPPED - python3/python not found (needed to merge the MCP config safely)."
}
if (Test-DesktopWired $script:ClaudeDesktopCfg) {
  $claudeDtStatus = "OK Claude Desktop wired to knowledge/ (scoped; read-write within it, no hooks) - $($script:ClaudeDesktopCfg) - paste $desktopInstr into its Project instructions"
} elseif ($script:ClaudeDesktopCfg) {
  $claudeDtStatus = "-- Claude Desktop not wired ($($script:ClaudeDesktopCfg)) - re-run with -InstallTools -WithDesktop, or wire manually if you don't use Claude Desktop"
} else {
  $claudeDtStatus = "-- Claude Desktop config path not detected" + $(if ($script:DesktopOsNote) { " ($($script:DesktopOsNote))" } else { "" })
}
if (Test-DesktopWired $script:ChatgptDesktopCfg) {
  $chatgptDtStatus = "OK ChatGPT Desktop wired to knowledge/ (scoped; read-write within it, no hooks) - $($script:ChatgptDesktopCfg) - paste $desktopInstr into its Project instructions"
} elseif ($script:ChatgptDesktopCfg) {
  $chatgptDtStatus = "-- ChatGPT Desktop not wired ($($script:ChatgptDesktopCfg)) - re-run with -InstallTools -WithDesktop, or wire manually if you don't use ChatGPT Desktop"
} else {
  $chatgptDtStatus = "-- ChatGPT Desktop config path not detected" + $(if ($script:DesktopOsNote) { " ($($script:DesktopOsNote))" } else { "" })
}

if ($GlobalOnly) {
  Write-Host ""
  Write-Host "OK Global bailiwick prerequisites installed/validated (no repo wired)."
  Write-Host "Next:"
  Write-Host "  - $tfStatus"
  Write-Host "  - $ghMcpStatus"
  Write-Host "  - $uvStatus"
  Write-Host "  - $hooksStatus"
  Write-Host "  - $skillStatus"
  Write-Host "  - $agentStageStatus"
  Write-Host "  - $mtAgentStatus"
  Write-Host "  - $codexSkillStatus"
  Write-Host "  - $codexStatus"
  Write-Host "  - $geminiStatus"
  Write-Host "  - $claudeDtStatus"
  Write-Host "  - $chatgptDtStatus"
  Write-Host "  - wire a repo:  bootstrap.ps1 <repo>   (shadow/zero-footprint by default; -Seeded for in-repo hidden wiring)"
} elseif ($Shadow) {
  # Reached only on a shadow run WITH -InstallTools (plain shadow runs exit in the shadow block).
  Write-Host ""
  Write-Host "OK Global bailiwick prerequisites installed/validated ('$RepoName' shadow-wired above - no repo files)."
  Write-Host "Next:"
  Write-Host "  - $tfStatus"
  Write-Host "  - $ghMcpStatus"
  Write-Host "  - $uvStatus"
  Write-Host "  - $hooksStatus"
  Write-Host "  - $skillStatus"
  Write-Host "  - $agentStageStatus"
  Write-Host "  - $mtAgentStatus"
  Write-Host "  - $codexSkillStatus"
  Write-Host "  - $codexStatus"
  Write-Host "  - $geminiStatus"
  Write-Host "  - $claudeDtStatus"
  Write-Host "  - $chatgptDtStatus"
} else {
  Write-Host ""
  Write-Host "OK Bootstrapped '$RepoName'."
  Write-Host "Next:"
  Write-Host "  - $ghStatusMsg"
  Write-Host "  - $tfStatus"
  Write-Host "  - $ghMcpStatus"
  Write-Host "  - $uvStatus"
  Write-Host "  - $hooksStatus"
  Write-Host "  - $skillStatus"
  Write-Host "  - $agentStageStatus"
  Write-Host "  - $mtAgentStatus"
  Write-Host "  - $codexSkillStatus"
  Write-Host "  - $codexStatus"
  if ($codexMcpStatus) { Write-Host "  - $codexMcpStatus" }
  Write-Host "  - $geminiStatus"
  Write-Host "  - $claudeDtStatus"
  Write-Host "  - $chatgptDtStatus"
  Write-Host "  - edit CLAUDE.local.md project-specific sections  (stack, environments, backend, CI/CD)"
}
