[CmdletBinding()]
param(
    [string]$AiccRoot = '.',
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path

$commands = @(
    @{ name='deployment-policy'; path='tools/platform/test/Test-AgentHomeDeploymentPolicy.ps1' },
    @{ name='directives'; path='tools/platform/test/Test-AgentHomeDirectives.ps1' },
    @{ name='skills'; path='tools/platform/inspect/Inspect-AgentSkills.ps1' },
    @{ name='guidance-sources'; path='tools/platform/inspect/Inspect-GuidanceSources.ps1' },
    @{ name='agents'; path='tools/platform/test/Test-CodexAgentDeployment.ps1' }
)
$results = @()
foreach ($command in $commands) {
    $raw = @(& pwsh -NoProfile -File (Join-Path $AiccRoot $command.path) -AiccRoot $AiccRoot -SummaryOnly -AsJson) -join "`n"
    $exitCode = $LASTEXITCODE
    $payload = try { $raw | ConvertFrom-Json } catch { $null }
    $results += [pscustomobject]@{
        name = $command.name
        ok = ($exitCode -eq 0 -and $null -ne $payload -and [bool]$payload.ok)
        exit_code = $exitCode
        result = $payload
    }
}
$failed = @($results | Where-Object { -not $_.ok })
$report = [ordered]@{
    ok = ($failed.Count -eq 0)
    aicc_root = $AiccRoot
    check_count = $results.Count
    failed_count = $failed.Count
    checks = $results
}
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 9 } else { $report | ConvertTo-Json -Depth 9 }
if ($failed.Count) { exit 1 }
