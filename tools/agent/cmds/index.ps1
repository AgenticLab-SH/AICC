# cmds/index.ps1 - `agent index` cross-agent metadata index
param(
    [Parameter(ValueFromRemainingArguments=$true)][object[]]$Args
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$AiccRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))
$inspect = Join-Path $AiccRoot 'tools\platform\inspect\Inspect-AgentSessions.ps1'
$aiccStateRoot = if ($env:AICC_STATE_ROOT) { $env:AICC_STATE_ROOT } else { Join-Path ([Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)) '.ai-control-center' }
$indexPath = Join-Path $aiccStateRoot 'session-index\all-agent-session-index.json'
$script:UserHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)

$Top = 30
$Refresh = $false
$Json = $false
foreach ($arg in @($Args)) {
    if ($null -eq $arg) { continue }
    $value = ([string]$arg).Trim()
    if ([string]::IsNullOrWhiteSpace($value)) { continue }
    if ($value -match '^\d+$') {
        $Top = [int]$value
        continue
    }
    switch ($value.ToLowerInvariant()) {
        'refresh' { $Refresh = $true; continue }
        '-refresh' { $Refresh = $true; continue }
        'json' { $Json = $true; continue }
        '-json' { $Json = $true; continue }
        default {
            Write-Host "Unknown agent index argument: $value" -ForegroundColor Red
            Write-Host "Usage: agent index [Top] [refresh] [json]" -ForegroundColor DarkGray
            exit 1
        }
    }
}

if ($Top -lt 1) { $Top = 1 }
if ($Top -gt 500) { $Top = 500 }

if ($Refresh -or -not (Test-Path -LiteralPath $indexPath)) {
    if (-not (Test-Path -LiteralPath $inspect)) {
        Write-Host "ERROR: missing session index tool: $inspect" -ForegroundColor Red
        exit 1
    }
    $null = & pwsh -NoProfile -ExecutionPolicy Bypass -File $inspect -Top 200 -WriteIndex -AsJson
}

if (-not (Test-Path -LiteralPath $indexPath)) {
    Write-Host "No session index found. Run: agent index -Refresh" -ForegroundColor Yellow
    exit 0
}

$data = Get-Content -LiteralPath $indexPath -Raw -Encoding UTF8 | ConvertFrom-Json
if ($Json) {
    $data | ConvertTo-Json -Depth 8
    return
}

function Shorten([string]$Text, [int]$Max) {
    if ([string]::IsNullOrWhiteSpace($Text)) { return '' }
    $value = $Text -replace [regex]::Escape($script:UserHome), '~'
    if ($value.Length -le $Max) { return $value }
    return $value.Substring(0, [Math]::Max(1, $Max - 2)) + '..'
}

Write-Host ""
Write-Host "Agent session index" -ForegroundColor Cyan
Write-Host ("  generated: {0}" -f $data.generated_at) -ForegroundColor DarkGray
Write-Host ("  roots: {0}/{1}  candidates: {2}  indexed: {3}  large: {4}" -f `
    $data.summary.existing_root_count,
    $data.summary.root_count,
    $data.summary.session_count,
    $data.summary.indexed_session_count,
    $data.summary.large_session_count) -ForegroundColor DarkGray
Write-Host ""

Write-Host "By agent" -ForegroundColor Yellow
foreach ($row in $data.by_agent) {
    Write-Host ("  {0,-12} {1,5} sessions  {2,8} MB  large {3}" -f $row.agent, $row.count, $row.total_mb, $row.large_count)
}

Write-Host ""
Write-Host ("Recent {0}" -f $Top) -ForegroundColor Yellow
Write-Host ("  {0,-4} {1,-12} {2,-16} {3,-8} {4}" -f '#', 'Agent', 'Kind', 'SizeMB', 'Source') -ForegroundColor DarkGray
Write-Host ("  " + ('-' * 92)) -ForegroundColor DarkGray

$i = 0
foreach ($session in @($data.sessions | Select-Object -First $Top)) {
    $i += 1
    Write-Host ("  {0,4} {1,-12} {2,-16} {3,8} {4}" -f `
        $i,
        (Shorten $session.agent 12),
        (Shorten $session.kind 16),
        $session.size_mb,
        (Shorten $session.source_path 52))
}

Write-Host ""
Write-Host "Tip: agent index refresh  |  agent index json" -ForegroundColor DarkGray
Write-Host ""
