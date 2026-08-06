[CmdletBinding()]
param(
  [string]$Url = 'whale://newtab/',
  [int]$TimeoutSec = 20,
  [switch]$LaunchIfMissing
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$aiccRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$coord = Join-Path $aiccRoot 'tools\platform\core\Read-AiccCoordination.ps1'
$identityGuard = Join-Path $PSScriptRoot 'Assert-CdpEndpointIdentity.ps1'
if (-not (Test-Path -LiteralPath $coord)) {
  throw "coordination reader not found: $coord"
}

$cdpUrl = (& pwsh -NoProfile -File $coord -Key browser.cdp_whale_url).Trim()
$profileDir = (& pwsh -NoProfile -File $coord -Key browser.cdp_whale_profile_dir 2>$null).Trim() -replace '/', '\'
$profileDirectory = (& pwsh -NoProfile -File $coord -Key browser.cdp_whale_profile_directory 2>$null).Trim()
if (-not $profileDirectory) { $profileDirectory = 'Profile 1' }
if ($cdpUrl -notmatch ':(\d+)(/)?$') {
  throw "Could not parse CDP port from $cdpUrl"
}
$port = [int]$Matches[1]

$whaleLauncher = Join-Path $HOME '.ai-control-center\browser-launchers\CDP Whale 9335.exe'

function Test-CdpResponding {
  param([string]$Endpoint)
  try {
    Invoke-RestMethod -Uri "$Endpoint/json/version" -TimeoutSec 2 | Out-Null
    return $true
  } catch {
    return $false
  }
}

function Test-CdpReady {
  param([string]$Endpoint)
  & pwsh -NoProfile -File $identityGuard `
    -ExpectedBrowser whale `
    -Endpoint $Endpoint `
    -ExpectedProfileDir $profileDir `
    -AsJson | Out-Null
  return $LASTEXITCODE -eq 0
}

function Get-CdpIdentityReport {
  param([string]$Endpoint)
  $output = & pwsh -NoProfile -File $identityGuard `
    -ExpectedBrowser whale `
    -Endpoint $Endpoint `
    -ExpectedProfileDir $profileDir `
    -AsJson
  return $output | ConvertFrom-Json
}

function Get-CdpWhaleProcesses {
  param([int]$DebugPort)
  @(
    Get-CimInstance Win32_Process -Filter "Name = 'whale.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and $_.CommandLine -match "--remote-debugging-port=$DebugPort(\s|$)" }
  )
}

if ((Test-CdpResponding -Endpoint $cdpUrl) -and -not (Test-CdpReady -Endpoint $cdpUrl)) {
  [pscustomobject]@{
    status = 'blocked'
    reason = 'cdp_endpoint_identity_mismatch'
    expected_browser = 'whale'
    cdp_url = $cdpUrl
    identity = Get-CdpIdentityReport -Endpoint $cdpUrl
    action = 'Stop. Do not fall back to Chrome or launch another browser on this port.'
  } | ConvertTo-Json -Compress -Depth 6
  exit 2
}

if (Test-CdpReady -Endpoint $cdpUrl) {
  [pscustomobject]@{
    status = 'ready'
    cdp_url = $cdpUrl
    profile_dir = $profileDir
    profile_directory = $profileDirectory
    launched = $false
  } | ConvertTo-Json -Compress
  exit 0
}

$whaleProcesses = Get-CdpWhaleProcesses -DebugPort $port
if ($whaleProcesses.Count -gt 0) {
  # A CDP Whale process exists but the endpoint did not answer yet; give it a moment.
  $deadline = (Get-Date).AddSeconds([Math]::Max($TimeoutSec, 1))
  do {
    if (Test-CdpReady -Endpoint $cdpUrl) {
      [pscustomobject]@{
        status = 'ready'
        cdp_url = $cdpUrl
        profile_dir = $profileDir
        profile_directory = $profileDirectory
        launched = $false
      } | ConvertTo-Json -Compress
      exit 0
    }
    Start-Sleep -Milliseconds 300
  } while ((Get-Date) -lt $deadline)
}

if (-not $LaunchIfMissing) {
  [pscustomobject]@{
    status = 'blocked'
    reason = 'cdp_whale_not_running'
    cdp_url = $cdpUrl
    profile_dir = $profileDir
    profile_directory = $profileDirectory
    action = 'Run start_shared_whale.ps1 -LaunchIfMissing (or launch "CDP Whale.exe") to start the dedicated CDP Whale profile.'
  } | ConvertTo-Json -Compress
  exit 2
}

if (-not (Test-Path -LiteralPath $whaleLauncher)) {
  throw "CDP Whale launcher not found: $whaleLauncher"
}

# CDP Whale.exe is idempotent: opens a tab if CDP is up, otherwise launches whale.exe
# with the dedicated non-default profile and the 9335 debugging port.
Start-Process -FilePath $whaleLauncher -ArgumentList $Url -WindowStyle Hidden | Out-Null

$deadline = (Get-Date).AddSeconds([Math]::Max($TimeoutSec, 1))
do {
  if (Test-CdpReady -Endpoint $cdpUrl) {
    [pscustomobject]@{
      status = 'ready'
      cdp_url = $cdpUrl
      profile_dir = $profileDir
      profile_directory = $profileDirectory
      launched = $true
    } | ConvertTo-Json -Compress
    exit 0
  }
  Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)

throw "CDP Whale endpoint did not become ready: $cdpUrl"
