[CmdletBinding()]
param(
    [string]$Profile = '00-career',
    [switch]$ScanNow
)

$ErrorActionPreference = 'Stop'
$aiccRoot = if ($env:AICC_ROOT) { $env:AICC_ROOT } else { (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../../..')).Path }
$scriptPath = Join-Path $aiccRoot 'tools/platform/sync/cross-device-sync-gui/cross_device_sync_web.py'
if (-not (Test-Path -LiteralPath $scriptPath -PathType Leaf)) { throw "GUI script missing: $scriptPath" }
$python = if ($IsWindows) {
    (Get-Command python -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
} else {
    (Get-Command python3 -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
}
$arguments = @($scriptPath, '--profile', $Profile, '--aicc-root', $aiccRoot)
& $python @arguments
