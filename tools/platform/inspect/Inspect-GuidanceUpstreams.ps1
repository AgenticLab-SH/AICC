[CmdletBinding()]
param(
    [string]$AiccRoot = '.',
    [switch]$IncludeInactive,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$ledgerPath = Join-Path $AiccRoot 'guidance/skills/aicc-guidance-review/references/absorption-ledger.json'
$ledger = Get-Content -LiteralPath $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json
$rows = @()

foreach ($source in @($ledger.sources)) {
    $monitor = $source.upstream_monitor
    if ([string]$monitor.mode -ne 'git-ls-remote') { continue }
    if (-not $IncludeInactive -and [string]$source.status -in @('rejected', 'duplicate', 'superseded')) { continue }
    $url = [string]$source.canonical_url
    if ($url -notmatch '^https://github\.com/([^/]+)/([^/]+?)(?:\.git)?$') {
        $rows += [pscustomobject]@{
            id = [string]$source.id
            status = 'unavailable'
            recorded_ref = [string]$monitor.latest_seen_ref
            current_ref = $null
            reason = 'canonical_url_not_supported_github_repo'
        }
        continue
    }
    $remoteUrl = "https://github.com/$($Matches[1])/$($Matches[2]).git"
    $raw = @(& git ls-remote $remoteUrl HEAD 2>$null) -join "`n"
    $exitCode = $LASTEXITCODE
    $currentRef = if ($exitCode -eq 0 -and $raw -match '^([0-9a-f]{40})\s') { $Matches[1] } else { $null }
    $recordedRef = [string]$monitor.latest_seen_ref
    $status = if (-not $currentRef) { 'unavailable' } elseif ($currentRef -eq $recordedRef) { 'current' } else { 'update_available' }
    $rows += [pscustomobject]@{
        id = [string]$source.id
        status = $status
        recorded_ref = $recordedRef
        current_ref = $currentRef
        reason = if ($currentRef) { $null } else { 'git_ls_remote_failed' }
    }
}

$report = [ordered]@{
    ok = (@($rows | Where-Object status -eq 'update_available').Count -eq 0)
    checked_at = (Get-Date).ToString('s')
    source_count = $rows.Count
    current_count = @($rows | Where-Object status -eq 'current').Count
    update_available_count = @($rows | Where-Object status -eq 'update_available').Count
    unavailable_count = @($rows | Where-Object status -eq 'unavailable').Count
    sources = $rows
}

if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 5 } else { $report | ConvertTo-Json -Depth 5 }
if (-not $report.ok) { exit 1 }
