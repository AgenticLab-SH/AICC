[CmdletBinding()]
param(
    [string]$ArchiveRoot = "$HOME/Archives/dev-migration/windows-browser-profiles-20260719",
    [string]$TargetRoot = "$HOME/.ai-control-center/browser-profiles/imported-windows"
)

$ErrorActionPreference = 'Stop'
if (-not $IsMacOS) { throw 'This importer is only for macOS.' }
$manifestPath = Join-Path $ArchiveRoot 'manifest.json'
if (-not (Test-Path -LiteralPath $manifestPath -PathType Leaf)) { throw 'Browser archive manifest is missing.' }
$manifest = Get-Content -LiteralPath $manifestPath -Raw | ConvertFrom-Json
$mapping = [ordered]@{
    'chrome-main.tar' = 'chrome-main'
    'chrome-cdp-primary.tar' = 'chrome-cdp-primary'
    'chrome-cdp-bulk.tar' = 'chrome-cdp-bulk'
    'whale-main.tar' = 'whale-main'
    'whale-cdp.tar' = 'whale-cdp'
}
$resolvedTarget = [IO.Path]::GetFullPath($TargetRoot)
New-Item -ItemType Directory -Force -Path $resolvedTarget | Out-Null
& chmod 700 $resolvedTarget
$records = @()

foreach ($item in @($manifest.items)) {
    $name = [string]$item.name
    if (-not $mapping.Contains($name)) { throw "Unexpected browser archive: $name" }
    $archive = Join-Path $ArchiveRoot $name
    if ((Get-Item -LiteralPath $archive).Length -ne [int64]$item.bytes) { throw "Archive size mismatch: $name" }
    $hash = (& shasum -a 256 $archive).Split(' ', [StringSplitOptions]::RemoveEmptyEntries)[0].ToLowerInvariant()
    if ($hash -ne ([string]$item.sha256).ToLowerInvariant()) { throw "Archive hash mismatch: $name" }
    $entries = @(& tar -tf $archive)
    foreach ($entry in $entries) {
        if ([string]::IsNullOrWhiteSpace($entry) -or $entry.StartsWith('/') -or $entry -match '(^|/)\.\.(/|$)') {
            throw "Unsafe tar entry in $name"
        }
    }
    $destination = [IO.Path]::GetFullPath((Join-Path $resolvedTarget $mapping[$name]))
    if (-not $destination.StartsWith($resolvedTarget + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)) {
        throw 'Browser extraction escaped the target root.'
    }
    if (Test-Path -LiteralPath $destination) { throw "Refusing to overwrite imported profile: $destination" }
    $partial = $destination + '.partial'
    if (Test-Path -LiteralPath $partial) { Remove-Item -LiteralPath $partial -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $partial | Out-Null
    & tar -xf $archive -C $partial
    if ($LASTEXITCODE -ne 0) { throw "Extraction failed: $name" }
    Get-ChildItem -LiteralPath $partial -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -in @('SingletonCookie', 'SingletonLock', 'SingletonSocket') } |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Move-Item -LiteralPath $partial -Destination $destination
    $files = @(Get-ChildItem -LiteralPath $destination -Recurse -File -Force)
    $records += [ordered]@{
        archive = $name
        destination = $mapping[$name]
        archive_sha256 = $hash
        tar_entries = $entries.Count
        extracted_files = $files.Count
        extracted_bytes = [int64](($files | Measure-Object Length -Sum).Sum)
    }
}

$result = [ordered]@{
    schema_version = 1
    completed_at = (Get-Date).ToString('o')
    archive_root = $ArchiveRoot
    target_root = $resolvedTarget
    records = $records
}
$result | ConvertTo-Json -Depth 6 | Set-Content -LiteralPath (Join-Path $resolvedTarget 'import-status.json') -Encoding utf8NoBOM
$result | ConvertTo-Json -Depth 6
