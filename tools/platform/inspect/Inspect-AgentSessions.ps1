#requires -Version 7.0
<#
.SYNOPSIS
  Metadata-first Codex and Claude session index for AICC.
.DESCRIPTION
  Scans configured Codex and Claude session roots. It records metadata only by
  default: path, size, last write time, inferred id, agent, kind, and resume
  hints. It does not delete, compress, move, vacuum, or read secret files.
#>
[CmdletBinding()]
param(
    [Alias('Hub')][string]$AiccRoot = (Join-Path $PSScriptRoot '../../..'),
    [string]$ConfigPath = '',
    [int]$RecentDays = 30,
    [int]$Top = 200,
    [double]$LargeSessionMB = 25,
    [switch]$WriteIndex,
    [switch]$IncludePreview,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ($Top -lt 1) { $Top = 1 }
if ($Top -gt 5000) { $Top = 5000 }

$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$aiccStateRoot = if ($env:AICC_STATE_ROOT) { $env:AICC_STATE_ROOT } else { Join-Path $HOME '.ai-control-center' }
$ConfigPath = if ($ConfigPath) { $ConfigPath } else { Join-Path $aiccStateRoot 'guidance/agent-session-index.toml' }
$IndexRoot = Join-Path $aiccStateRoot 'session-index'
$IndexPath = Join-Path $IndexRoot 'all-agent-session-index.json'
$now = Get-Date

function Convert-ToPlatformPath {
    param([string]$Value)
    if ([string]::IsNullOrWhiteSpace($Value)) { return $Value }
    if ($IsWindows) { return ($Value -replace '/', '\') }
    return ($Value -replace '\\', '/')
}

function Convert-BytesToMB {
    param([double]$Bytes)
    return [math]::Round(($Bytes / 1MB), 2)
}

function Get-RelativePathSafe {
    param([string]$Root, [string]$Path)
    try {
        $rootFull = [System.IO.Path]::GetFullPath($Root).TrimEnd('\') + '\'
        $pathFull = [System.IO.Path]::GetFullPath($Path)
        if ($pathFull.StartsWith($rootFull, [System.StringComparison]::OrdinalIgnoreCase)) {
            return $pathFull.Substring($rootFull.Length)
        }
    } catch {}
    return $Path
}

function Read-SessionIndexConfig {
    param([string]$Path)
    $roots = @()
    if (-not (Test-Path -LiteralPath $Path)) { return $roots }
    $current = $null
    foreach ($raw in @(Get-Content -LiteralPath $Path -Encoding UTF8)) {
        $line = $raw.Trim()
        if ([string]::IsNullOrWhiteSpace($line) -or $line.StartsWith('#')) { continue }
        if ($line -eq '[[roots]]') {
            if ($null -ne $current) { $roots += [pscustomobject]$current }
            $current = [ordered]@{}
            continue
        }
        if ($null -ne $current -and $line -match '^([A-Za-z0-9_\-]+)\s*=\s*(.+)$') {
            $key = $Matches[1]
            $value = $Matches[2].Trim()
            if ($value -match '^"(.*)"$') { $value = $Matches[1] }
            elseif ($value -eq 'true') { $value = $true }
            elseif ($value -eq 'false') { $value = $false }
            $current[$key] = $value
        }
    }
    if ($null -ne $current) { $roots += [pscustomobject]$current }
    return $roots
}

function Get-SessionIdFromFile {
    param(
        [string]$Agent,
        [System.IO.FileInfo]$File
    )
    $base = [System.IO.Path]::GetFileNameWithoutExtension($File.Name)
    if ($Agent -eq 'Codex' -and $base -match '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})$') {
        return $Matches[1]
    }
    if ($base -match '([0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12})') {
        return $Matches[1]
    }
    return $base
}

function Get-ResumeHint {
    param(
        [string]$Agent,
        [string]$SessionId,
        [string]$Cwd
    )
    switch ($Agent) {
        'Codex' { return "agent sessions -> Codex -> $SessionId" }
        'Claude' { return "agent sessions -> Claude -> $SessionId" }
        default { return "inspect source path" }
    }
}

function Try-ReadCwd {
    param(
        [string]$Agent,
        [System.IO.FileInfo]$File,
        [switch]$AllowContentRead
    )
    if (-not $AllowContentRead) { return '' }
    if ($File.Length -gt 5MB) { return '' }
    try {
        $line = Get-Content -LiteralPath $File.FullName -TotalCount 1 -Encoding UTF8 -ErrorAction Stop
        if ($line -match '"cwd"\s*:\s*"([^"]+)"') {
            return ($Matches[1] -replace '\\\\','\')
        }
        if ($line -match '"project"\s*:\s*"([^"]+)"') {
            return ($Matches[1] -replace '\\\\','\')
        }
    } catch {}
    return ''
}

$roots = @(Read-SessionIndexConfig -Path $ConfigPath)
$allItems = @()
$rootStats = @()

foreach ($root in $roots) {
    $path = Convert-ToPlatformPath -Value ([string]$root.path)
    $exists = Test-Path -LiteralPath $path
    $rootItems = @()
    if ($exists) {
        $pattern = if ($root.pattern) { [string]$root.pattern } else { '*' }
        $recurse = ($root.recursive -eq $true)
        $rootItems = @(Get-ChildItem -LiteralPath $path -Filter $pattern -File -Force -Recurse:$recurse -ErrorAction SilentlyContinue)
        foreach ($file in $rootItems) {
            $sessionId = Get-SessionIdFromFile -Agent ([string]$root.agent) -File $file
            $cwd = Try-ReadCwd -Agent ([string]$root.agent) -File $file -AllowContentRead:$IncludePreview
            $ageDays = [math]::Round((New-TimeSpan -Start $file.LastWriteTime -End $now).TotalDays, 2)
            $sizeMB = Convert-BytesToMB -Bytes ([double]$file.Length)
            $status = if ($ageDays -le $RecentDays) { 'recent' } else { 'old' }
            if ([string]$root.agent -eq 'AICC' -and [string]$root.kind -eq 'active-work') {
                try {
                    $json = Get-Content -LiteralPath $file.FullName -Raw -Encoding UTF8 | ConvertFrom-Json
                    if ($json.status) { $status = [string]$json.status }
                    if (-not $cwd -and $json.workspace) { $cwd = [string]$json.workspace }
                    if ($json.thread_id) { $sessionId = [string]$json.thread_id }
                } catch {}
            }
            $allItems += [pscustomobject]@{
                agent = [string]$root.agent
                kind = [string]$root.kind
                session_id = $sessionId
                status = $status
                cwd = $cwd
                source_path = $file.FullName
                relative_path = Get-RelativePathSafe -Root $path -Path $file.FullName
                size_mb = $sizeMB
                last_activity = $file.LastWriteTime.ToString('s')
                age_days = $ageDays
                large = ($sizeMB -ge $LargeSessionMB)
                resume_hint = Get-ResumeHint -Agent ([string]$root.agent) -SessionId $sessionId -Cwd $cwd
            }
        }
    }
    $rootStats += [pscustomobject]@{
        agent = [string]$root.agent
        kind = [string]$root.kind
        path = $path
        exists = $exists
        count = @($rootItems).Count
    }
}

$items = @($allItems | Sort-Object last_activity -Descending | Select-Object -First $Top)
$summaryByAgent = @($allItems | Group-Object agent | ForEach-Object {
    [pscustomobject]@{
        agent = $_.Name
        count = $_.Count
        large_count = @($_.Group | Where-Object { $_.large }).Count
        total_mb = [math]::Round((($_.Group | Measure-Object size_mb -Sum).Sum), 2)
        recent_count = @($_.Group | Where-Object { $_.status -eq 'recent' }).Count
    }
} | Sort-Object agent)

$largeItems = @($allItems | Where-Object { $_.large } | Sort-Object size_mb -Descending | Select-Object -First 20)

$result = [ordered]@{
    ok = $true
    generated_at = (Get-Date).ToString('o')
    config_path = $ConfigPath
    write_index = [bool]$WriteIndex
    include_preview = [bool]$IncludePreview
    policy = 'metadata-first; no cleanup; no session content preview unless IncludePreview is used'
    summary = [pscustomobject]@{
        root_count = $roots.Count
        existing_root_count = @($rootStats | Where-Object { $_.exists }).Count
        session_count = $allItems.Count
        indexed_session_count = $items.Count
        large_session_count = @($allItems | Where-Object { $_.large }).Count
        recent_days = $RecentDays
        destructive_actions = 0
    }
    by_agent = $summaryByAgent
    roots = $rootStats
    large_sessions = $largeItems
    sessions = $items
    index_path = if ($WriteIndex) { $IndexPath } else { $null }
}

if ($WriteIndex) {
    New-Item -ItemType Directory -Force -Path $IndexRoot | Out-Null
    $result | ConvertTo-Json -Depth 8 | Set-Content -LiteralPath $IndexPath -Encoding UTF8
}

if ($AsJson) {
    $result | ConvertTo-Json -Depth 8
} else {
    $result
}
