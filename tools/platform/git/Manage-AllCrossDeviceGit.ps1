[CmdletBinding()]
param(
    [ValidateSet('Status','Sync','Pull','Push','Configure')][string]$Action = 'Status',
    [string]$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path,
    [string]$ConfigPath
)

$ErrorActionPreference = 'Stop'
$AiccRoot = [IO.Path]::GetFullPath($AiccRoot)
if (-not $ConfigPath) { $ConfigPath = Join-Path $HOME '.ai-control-center/cross-device/repositories.json' }
$config = Get-Content -LiteralPath $ConfigPath -Raw | ConvertFrom-Json
$devRoot = [string]$config.dev_root
if ($devRoot.StartsWith('~/') -or $devRoot.StartsWith('~\')) { $devRoot = Join-Path $HOME $devRoot.Substring(2) }
if (-not [IO.Path]::IsPathRooted($devRoot)) { throw 'Private repository config requires an absolute dev_root.' }
$devRoot = [IO.Path]::GetFullPath($devRoot)
$worker = Join-Path $AiccRoot 'tools/platform/git/Manage-CrossDeviceGit.ps1'
if (-not (Test-Path -LiteralPath $worker -PathType Leaf)) { throw "Git worker missing: $worker" }

$results = @()
$failures = @()
foreach ($item in @($config.repositories)) {
    $configuredPath = [string]$item.path
    $repo = if ([IO.Path]::IsPathRooted($configuredPath)) { [IO.Path]::GetFullPath($configuredPath) } else { [IO.Path]::GetFullPath((Join-Path $devRoot $configuredPath)) }
    if (-not (Test-Path -LiteralPath (Join-Path $repo '.git'))) {
        $failures += [ordered]@{name=$item.name;repo=$repo;error='repository-missing'}
        continue
    }
    try {
        $remoteName = if ($item.PSObject.Properties.Name -contains 'remote' -and $item.remote) { [string]$item.remote } else { [string]$config.remote }
        $raw = & pwsh -NoProfile -File $worker -Action $Action -Repository $repo -RemoteName $remoteName
        if ($LASTEXITCODE -ne 0) { throw "worker-exit-$LASTEXITCODE" }
        $results += [ordered]@{name=$item.name;repo=$repo;remote=$remoteName;result=($raw | ConvertFrom-Json)}
    } catch {
        $failures += [ordered]@{name=$item.name;repo=$repo;error=$_.Exception.Message}
    }
}
$summary = [ordered]@{
    ok = ($failures.Count -eq 0)
    action = $Action
    checked_at = (Get-Date).ToString('o')
    repository_count = @($config.repositories).Count
    success_count = $results.Count
    failure_count = $failures.Count
    results = $results
    failures = $failures
}
$summary | ConvertTo-Json -Depth 8
if ($failures.Count -gt 0) { exit 1 }
