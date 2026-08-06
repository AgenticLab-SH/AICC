[CmdletBinding()]
param(
    [string]$AiccRoot = '.',
    [switch]$SummaryOnly,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$raw = @(& node (Join-Path $AiccRoot 'src/cli.mjs') agents check --json) -join "`n"
$exitCode = $LASTEXITCODE
$payload = try { $raw | ConvertFrom-Json } catch { $null }
$report = [ordered]@{
    ok = ($exitCode -eq 0 -and $null -ne $payload -and [bool]$payload.ok)
    agent_count = if ($payload) { [int]$payload.summary.comparedFiles } else { 0 }
    deployment_issue_count = if ($payload) { @($payload.issues).Count } else { 1 }
    manifest_issue_count = if ($payload -and $payload.summary.manifestUpdate) { 1 } else { 0 }
}
if (-not $SummaryOnly) {
    $report['issues'] = if ($payload) { @($payload.issues) } else { @('Codex agent JSON을 읽지 못했습니다.') }
}
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 6 } else { $report | ConvertTo-Json -Depth 6 }
if (-not $report.ok) { exit 1 }
