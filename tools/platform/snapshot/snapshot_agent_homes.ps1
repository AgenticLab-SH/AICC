# snapshot_agent_homes.ps1 - config-only recovery snapshot for Codex/Claude homes.
#
# Captures rules, hooks, commands, prompts, skills, and config files while
# excluding credentials, auth state, sessions, browser profiles, logs, caches,
# sqlite databases, and other runtime material.

[CmdletBinding()]
param(
    [string]$CodexHome = (Join-Path $HOME '.codex'),
    [string]$ClaudeHome = (Join-Path $HOME '.claude'),
    [string]$OutputDir = (Join-Path $HOME '.ai-control-center/backups/agent-homes'),
    [string]$Reason = 'manual agent home config snapshot',
    [int]$MaxFileBytes = 2097152,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.IO.Compression.FileSystem

$homes = @(
    [pscustomobject]@{
        label = 'codex'
        root = (Resolve-Path -LiteralPath $CodexHome).Path
        includes = @('AGENTS.md', 'config.toml', 'hooks.json', '.shared_chrome_env', 'agents', 'bin', 'custom_skills', 'prompts', 'rules', 'skills', 'src')
    },
    [pscustomobject]@{
        label = 'claude'
        root = (Resolve-Path -LiteralPath $ClaudeHome).Path
        includes = @('CLAUDE.md', 'settings.json', 'settings.local.json', 'agents', 'commands', 'hooks', 'skills')
    }
)

New-Item -ItemType Directory -Force -Path $OutputDir | Out-Null
$timestamp = Get-Date -Format 'yyyyMMdd_HHmmss'
$baseName = "agent-homes_$timestamp"
$zipPath = Join-Path $OutputDir "$baseName.zip"
$manifestPath = Join-Path $OutputDir "$baseName.manifest.json"

$excludePathRegex = @(
    '\\(\.git|__pycache__|\.pytest_cache|node_modules)(\\|$)',
    '\\(browser|cache|downloads|file-history|logs?|paste-cache|plugins|projects|sessions?|shell-snapshots|tasks|telemetry|tmp|\.tmp|vendor)(\\|$)',
    '\\(\.sandbox|\.sandbox-bin|\.sandbox-secrets)(\\|$)',
    '\.sqlite($|[.-])',
    '\.log$',
    '\.zip$',
    '\.7z$',
    '\.tar$',
    '\.tgz$',
    '\.pyc$',
    'history\.jsonl$',
    'session_index\.jsonl$',
    'auth\.json$',
    '\.credentials\.json$',
    'installation_id$',
    'cap_sid$',
    'models_cache\.json$',
    'stats-cache\.json$'
) -join '|'

$secretValueRegex = '(?i)(sk-[A-Za-z0-9_\-]{20,}|github_pat_[A-Za-z0-9_]{20,}|ghp_[A-Za-z0-9_]{20,}|xox[baprs]-[A-Za-z0-9\-]{20,}|AKIA[0-9A-Z]{16}|BEGIN (RSA|OPENSSH|PRIVATE) KEY)'

function Get-RelativePath {
    param([string]$Root, [string]$Path)
    $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
    $pathFull = [System.IO.Path]::GetFullPath($Path)
    $pathFull.Substring($rootFull.Length)
}

function Test-SecretLikeContent {
    param([string]$Path)
    try {
        $sample = Get-Content -LiteralPath $Path -Raw -ErrorAction Stop
        return ($sample -match $secretValueRegex)
    } catch {
        return $true
    }
}

$selected = New-Object System.Collections.Generic.List[object]
$skipped = New-Object System.Collections.Generic.List[object]

foreach ($agentHome in $homes) {
    foreach ($include in $agentHome.includes) {
        $path = Join-Path $agentHome.root $include
        if (-not (Test-Path -LiteralPath $path)) {
            continue
        }
        $item = Get-Item -LiteralPath $path -Force
        $candidates = if ($item.PSIsContainer) {
            Get-ChildItem -LiteralPath $item.FullName -Recurse -File -Force -ErrorAction SilentlyContinue
        } else {
            @($item)
        }
        foreach ($file in $candidates) {
            $relative = Get-RelativePath -Root $agentHome.root -Path $file.FullName
            $entryPath = "$($agentHome.label)/$($relative -replace '\\', '/')"
            if ($file.FullName -match $excludePathRegex -or $relative -match $excludePathRegex) {
                [void]$skipped.Add([ordered]@{ path = $entryPath; reason = 'excluded_path' })
                continue
            }
            if ($file.Length -gt $MaxFileBytes) {
                [void]$skipped.Add([ordered]@{ path = $entryPath; reason = 'too_large'; length = $file.Length })
                continue
            }
            if (Test-SecretLikeContent -Path $file.FullName) {
                [void]$skipped.Add([ordered]@{ path = $entryPath; reason = 'secret_like_content' })
                continue
            }
            [void]$selected.Add([pscustomobject]@{
                label = $agentHome.label
                root = $agentHome.root
                full_name = $file.FullName
                entry_path = $entryPath
                length = $file.Length
                last_write = $file.LastWriteTime.ToString('o')
            })
        }
    }
}

$unique = @($selected | Sort-Object entry_path -Unique)
if ($unique.Count -eq 0) {
    throw 'No files selected for agent home snapshot.'
}
if (Test-Path -LiteralPath $zipPath) {
    throw "Snapshot already exists: $zipPath"
}

$zip = [System.IO.Compression.ZipFile]::Open($zipPath, [System.IO.Compression.ZipArchiveMode]::Create)
try {
    foreach ($file in $unique) {
        [System.IO.Compression.ZipFileExtensions]::CreateEntryFromFile($zip, $file.full_name, $file.entry_path, [System.IO.Compression.CompressionLevel]::Optimal) | Out-Null
    }
} finally {
    $zip.Dispose()
}

$manifestFiles = @()
foreach ($file in $unique) {
    $manifestFiles += [ordered]@{
        path = $file.entry_path
        source = $file.full_name
        length = $file.length
        last_write = $file.last_write
        sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $file.full_name).Hash
    }
}

$manifestFilesArray = @($manifestFiles)
$skippedArray = @($skipped.ToArray())

$manifest = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    reason = $Reason
    zip_path = $zipPath
    manifest_path = $manifestPath
    codex_home = $homes[0].root
    claude_home = $homes[1].root
    file_count = @($manifestFiles).Count
    zip_length = (Get-Item -LiteralPath $zipPath).Length
    max_file_bytes = $MaxFileBytes
    excluded = @('auth', 'credentials', 'history', 'sessions', 'logs', 'sqlite', 'browser', 'cache', 'plugins', 'telemetry', 'runtime state')
    skipped = $skippedArray
    files = $manifestFilesArray
}

$manifest | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath $manifestPath -Encoding UTF8

$summary = [ordered]@{
    status = 'snapshotted'
    zip_path = $zipPath
    manifest_path = $manifestPath
    file_count = $manifest.file_count
    zip_length = $manifest.zip_length
    skipped_count = $skippedArray.Count
}

if ($AsJson) {
    $summary | ConvertTo-Json -Compress -Depth 4
    return
}

Write-Host ''
Write-Host '=== Agent Homes Config Snapshot ===' -ForegroundColor Cyan
Write-Host ("Zip      : {0}" -f $zipPath)
Write-Host ("Manifest : {0}" -f $manifestPath)
Write-Host ("Files    : {0}" -f $manifest.file_count)
Write-Host ("Skipped  : {0}" -f $skippedArray.Count)
Write-Host ("Bytes    : {0}" -f $manifest.zip_length)
Write-Host ''
