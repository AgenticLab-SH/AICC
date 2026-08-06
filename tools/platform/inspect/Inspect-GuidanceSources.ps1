[CmdletBinding()]
param(
    [string]$AiccRoot = '.',
    [switch]$SummaryOnly,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$ledgerPath = Join-Path $AiccRoot 'guidance/skills/aicc-guidance-review/references/absorption-ledger.json'
$issues = @()

if (-not (Test-Path -LiteralPath $ledgerPath -PathType Leaf)) {
    $issues += 'absorption ledger missing'
    $ledger = $null
} else {
    try { $ledger = Get-Content -LiteralPath $ledgerPath -Raw -Encoding UTF8 | ConvertFrom-Json } catch {
        $issues += 'absorption ledger invalid JSON'
        $ledger = $null
    }
}

$allowedStatus = @('pending', 'researching', 'absorbed', 'duplicate', 'deferred', 'rejected', 'superseded')
$allowedKind = @('vendored', 'copied', 'pattern', 'ui-pattern', 'dependency', 'model', 'data', 'tool', 'official-doc')
$allowedVerification = @('passed', 'failed', 'partial', 'not_run')
$ids = @{}
$urls = @{}
$sourceCount = 0

if ($ledger) {
    if ([int]$ledger.schema_version -ne 1) { $issues += 'unsupported schema_version' }
    foreach ($source in @($ledger.sources)) {
        $sourceCount += 1
        $id = [string]$source.id
        $url = [string]$source.canonical_url
        if ($id -notmatch '^[a-z0-9]+(?:-[a-z0-9]+)*$') { $issues += "invalid id: $id" }
        if ($ids.ContainsKey($id)) { $issues += "duplicate id: $id" } else { $ids[$id] = $true }
        if ($url -notmatch '^https://') { $issues += "canonical_url must use https: $id" }
        if ($urls.ContainsKey($url)) { $issues += "duplicate canonical_url: $id" } else { $urls[$url] = $id }
        if ([string]$source.status -notin $allowedStatus) { $issues += "invalid status: $id" }
        if ([string]$source.kind -notin $allowedKind) { $issues += "invalid kind: $id" }
        foreach ($field in @('first_seen_at', 'last_verified_at')) {
            $value = [string]$source.$field
            $parsed = [datetime]::MinValue
            if (-not [datetime]::TryParseExact($value, 'yyyy-MM-dd', $null, [Globalization.DateTimeStyles]::None, [ref]$parsed)) {
                $issues += "invalid $field`: $id"
            }
        }
        if (-not $source.license -or [string]::IsNullOrWhiteSpace([string]$source.license.status)) { $issues += "missing license: $id" }
        if (-not $source.decision -or [string]::IsNullOrWhiteSpace([string]$source.decision.summary)) { $issues += "missing decision: $id" }
        if ([string]$source.verification.status -notin $allowedVerification) { $issues += "invalid verification: $id" }
        if (-not $source.upstream_monitor -or [string]::IsNullOrWhiteSpace([string]$source.upstream_monitor.next_due)) { $issues += "missing upstream monitor: $id" }
        $targets = @($source.targets)
        if ([string]$source.status -eq 'absorbed' -and $targets.Count -eq 0) { $issues += "absorbed source has no target: $id" }
        foreach ($target in $targets) {
            $targetText = [string]$target
            if ([IO.Path]::IsPathRooted($targetText) -or $targetText -match '(^|/|\\)\.\.($|/|\\)') {
                $issues += "unsafe target path: $id"
                continue
            }
            if (-not (Test-Path -LiteralPath (Join-Path $AiccRoot $targetText))) { $issues += "missing target: $id -> $targetText" }
        }
        $serialized = $source | ConvertTo-Json -Compress -Depth 9
        if ($serialized -match '(?i)(api[_-]?key|bearer\s+[a-z0-9._-]+|/Users/|\\Users\\|session[_-]?token)') {
            $issues += "private or secret-like value: $id"
        }
    }
}

$report = [ordered]@{
    ok = ($issues.Count -eq 0)
    ledger = $ledgerPath
    source_count = $sourceCount
    issue_count = $issues.Count
}
if (-not $SummaryOnly) { $report['issues'] = @($issues) }
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 6 } else { $report | ConvertTo-Json -Depth 6 }
if ($issues.Count) { exit 1 }
