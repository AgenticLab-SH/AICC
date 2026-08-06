# verify_agent_homes_snapshot.ps1 - read-only verifier for agent home config snapshots.

[CmdletBinding()]
param(
    [string]$ManifestPath,
    [string]$SnapshotDir = (Join-Path $HOME '.ai-control-center/backups/agent-homes'),
    [switch]$SummaryOnly,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

Add-Type -AssemblyName System.IO.Compression.FileSystem

if ([string]::IsNullOrWhiteSpace($ManifestPath)) {
    $latest = Get-ChildItem -LiteralPath $SnapshotDir -Filter 'agent-homes_*.manifest.json' -File -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending |
        Select-Object -First 1
    if (-not $latest) {
        throw "No agent home snapshot manifest found in $SnapshotDir"
    }
    $ManifestPath = $latest.FullName
}

$manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
$zipPath = [string]$manifest.zip_path
if ([string]::IsNullOrWhiteSpace($zipPath)) {
    $zipPath = $ManifestPath -replace '\.manifest\.json$', '.zip'
}

$forbiddenPathRegex = '(?i)(^|/)(auth\.json|\.credentials\.json|history\.jsonl|session_index\.jsonl|installation_id|cap_sid|models_cache\.json|stats-cache\.json)$|/(browser|cache|downloads|file-history|logs?|paste-cache|plugins|projects|sessions?|shell-snapshots|tasks|telemetry|tmp|vendor)/|\.sqlite($|[.-])|\.log$'

$zipExists = Test-Path -LiteralPath $zipPath
$entries = @()
if ($zipExists -and -not $SummaryOnly) {
    $zip = [System.IO.Compression.ZipFile]::OpenRead($zipPath)
    try {
        $entries = @($zip.Entries | Where-Object { -not [string]::IsNullOrWhiteSpace($_.Name) } | ForEach-Object {
            [pscustomobject]@{ path = $_.FullName; length = $_.Length }
        })
    } finally {
        $zip.Dispose()
    }
}

$manifestFiles = @($manifest.files)
$manifestPaths = @($manifestFiles | ForEach-Object { [string]$_.path })
$entryPaths = @($entries | ForEach-Object { [string]$_.path })
$entryLengthByPath = @{}
foreach ($entry in $entries) {
    $entryLengthByPath[[string]$entry.path] = [int64]$entry.length
}

$duplicateManifestPaths = @($manifestPaths | Group-Object | Where-Object { $_.Count -gt 1 } | ForEach-Object { $_.Name })
$missingInZip = @($manifestPaths | Where-Object { $_ -notin $entryPaths })
$extraInZip = @($entryPaths | Where-Object { $_ -notin $manifestPaths })
$forbiddenManifest = @($manifestPaths | Where-Object { $_ -match $forbiddenPathRegex })
$forbiddenZip = @($entryPaths | Where-Object { $_ -match $forbiddenPathRegex })
$sizeMismatches = @()

foreach ($file in $manifestFiles) {
    $path = [string]$file.path
    if ($entryLengthByPath.ContainsKey($path) -and ([int64]$entryLengthByPath[$path] -ne [int64]$file.length)) {
        $sizeMismatches += [ordered]@{ path = $path; manifest_length = [int64]$file.length; zip_length = [int64]$entryLengthByPath[$path] }
    }
}

$warnings = New-Object System.Collections.Generic.List[string]
if (-not $zipExists) { [void]$warnings.Add('zip file missing') }
if ($duplicateManifestPaths.Count -gt 0) { [void]$warnings.Add('duplicate manifest paths found') }
if (-not $SummaryOnly -and $missingInZip.Count -gt 0) { [void]$warnings.Add('manifest paths missing in zip') }
if (-not $SummaryOnly -and $extraInZip.Count -gt 0) { [void]$warnings.Add('zip contains paths not in manifest') }
if ($forbiddenManifest.Count -gt 0 -or (-not $SummaryOnly -and $forbiddenZip.Count -gt 0)) { [void]$warnings.Add('forbidden runtime/credential paths detected') }
if (-not $SummaryOnly -and $sizeMismatches.Count -gt 0) { [void]$warnings.Add('size mismatches detected') }

$report = [ordered]@{
    timestamp = (Get-Date).ToString('o')
    ok = ($warnings.Count -eq 0)
    manifest_path = $ManifestPath
    zip_path = $zipPath
    zip_exists = $zipExists
    mode = if ($SummaryOnly) { 'summary-metadata' } else { 'full-zip-entry' }
    manifest_file_count = [int]$manifest.file_count
    manifest_files_array_count = $manifestFiles.Count
    zip_entry_count = $entries.Count
    zip_length = if ($zipExists) { (Get-Item -LiteralPath $zipPath).Length } else { 0 }
    skipped_count = @($manifest.skipped).Count
    duplicate_manifest_paths = @($duplicateManifestPaths)
    missing_in_zip = @($missingInZip)
    extra_in_zip = @($extraInZip)
    forbidden_manifest_paths = @($forbiddenManifest)
    forbidden_zip_paths = @($forbiddenZip)
    size_mismatches = @($sizeMismatches)
    warnings = @($warnings)
}

if ($AsJson) {
    $report | ConvertTo-Json -Compress -Depth 6
    return
}

Write-Host ''
Write-Host '=== Agent Homes Snapshot Verification ===' -ForegroundColor Cyan
Write-Host ("OK       : {0}" -f $report.ok)
Write-Host ("Manifest : {0}" -f $report.manifest_path)
Write-Host ("Zip      : {0}" -f $report.zip_path)
Write-Host ("Files    : manifest={0}, zip={1}" -f $report.manifest_files_array_count, $report.zip_entry_count)
if ($report.warnings.Count -gt 0) {
    Write-Host ''
    Write-Host '--- warnings ---' -ForegroundColor Yellow
    foreach ($w in $report.warnings) { Write-Host ("  * {0}" -f $w) -ForegroundColor Yellow }
}
Write-Host ''
