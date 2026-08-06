[CmdletBinding()]
param(
  [string]$Url = 'about:blank',
  [int]$TimeoutSec = 15,
  [switch]$LaunchIfMissing,
  # Optional slot overrides. When omitted, slot1 values from coordination.toml
  # (cdp_url / cdp_profile_dir / cdp_profile_directory) are used for backward compat.
  [int]$Port = 0,
  [string]$ProfileDir = '',
  [string]$ProfileDirectory = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$aiccRoot = [IO.Path]::GetFullPath((Join-Path $PSScriptRoot '..\..\..'))
$coord = Join-Path $aiccRoot 'tools\platform\core\Read-AiccCoordination.ps1'
$identityGuard = Join-Path $PSScriptRoot 'Assert-CdpEndpointIdentity.ps1'
if (-not (Test-Path -LiteralPath $coord)) {
  throw "coordination reader not found: $coord"
}

$realProfileDir = (& pwsh -NoProfile -File $coord -Key browser.profile_dir).Trim() -replace '/', '\'

# Port: explicit -Port wins, else parse slot1 cdp_url.
if ($Port -gt 0) {
  $port = $Port
} else {
  $cdpUrl0 = (& pwsh -NoProfile -File $coord -Key browser.cdp_url).Trim()
  if ($cdpUrl0 -notmatch ':(\d+)(/)?$') {
    throw "Could not parse CDP port from $cdpUrl0"
  }
  $port = [int]$Matches[1]
}
$cdpUrl = "http://127.0.0.1:$port"

# Profile dir: explicit -ProfileDir wins, else slot1 cdp_profile_dir, else real profile.
if ($ProfileDir) {
  $profileDir = $ProfileDir -replace '/', '\'
} else {
  $profileDir = (& pwsh -NoProfile -File $coord -Key browser.cdp_profile_dir 2>$null).Trim() -replace '/', '\'
  if (-not $profileDir) { $profileDir = $realProfileDir }
}

if ($ProfileDirectory) {
  $profileDirectory = $ProfileDirectory
} else {
  $profileDirectory = (& pwsh -NoProfile -File $coord -Key browser.cdp_profile_directory 2>$null).Trim()
  if (-not $profileDirectory) { $profileDirectory = 'Default' }
}

$defaultChromeUserData = (Join-Path $env:LocalAppData 'Google\Chrome\User Data')
$isDefaultChromeUserData = [string]::Equals(
  [IO.Path]::GetFullPath($profileDir).TrimEnd('\'),
  [IO.Path]::GetFullPath($defaultChromeUserData).TrimEnd('\'),
  [StringComparison]::OrdinalIgnoreCase
)

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
    -ExpectedBrowser chrome `
    -Endpoint $Endpoint `
    -ExpectedProfileDir $profileDir `
    -AsJson | Out-Null
  return $LASTEXITCODE -eq 0
}

function Get-CdpIdentityReport {
  param([string]$Endpoint)
  $output = & pwsh -NoProfile -File $identityGuard `
    -ExpectedBrowser chrome `
    -Endpoint $Endpoint `
    -ExpectedProfileDir $profileDir `
    -AsJson
  return $output | ConvertFrom-Json
}

function Get-CdpChromeProcesses {
  param([int]$DebugPort)
  @(
    Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue |
      Where-Object { $_.CommandLine -and $_.CommandLine -match "--remote-debugging-port=$DebugPort(\s|$)" }
  )
}

if ((Test-CdpResponding -Endpoint $cdpUrl) -and -not (Test-CdpReady -Endpoint $cdpUrl)) {
  [pscustomobject]@{
    status = 'blocked'
    reason = 'cdp_endpoint_identity_mismatch'
    expected_browser = 'chrome'
    cdp_url = $cdpUrl
    identity = Get-CdpIdentityReport -Endpoint $cdpUrl
    action = 'Stop. Do not fall back to Whale or launch another browser on this port.'
  } | ConvertTo-Json -Compress -Depth 6
  exit 2
}

if (Test-CdpReady -Endpoint $cdpUrl) {
  $cdpProcesses = Get-CdpChromeProcesses -DebugPort $port
  $matchingProcesses = @($cdpProcesses | Where-Object { $_.CommandLine -match [regex]::Escape($profileDir) })
  if ($cdpProcesses.Count -gt 0 -and $matchingProcesses.Count -eq 0) {
    [pscustomobject]@{
      status = 'blocked'
      reason = 'cdp_running_with_wrong_profile'
      cdp_url = $cdpUrl
      expected_profile_dir = $profileDir
      real_profile_dir = $realProfileDir
      action = "Close the existing $port Chrome and relaunch with start_shared_chrome.ps1 -LaunchIfMissing so CDP uses the dedicated non-default profile."
      chrome_pids = @($cdpProcesses | Select-Object -ExpandProperty ProcessId)
    } | ConvertTo-Json -Compress
    exit 2
  }
  [pscustomobject]@{
    status = 'ready'
    cdp_url = $cdpUrl
    profile_dir = $profileDir
    profile_directory = $profileDirectory
    real_profile_dir = $realProfileDir
    launched = $false
  } | ConvertTo-Json -Compress
  exit 0
}

if ($isDefaultChromeUserData) {
  [pscustomobject]@{
    status = 'blocked'
    reason = 'cdp_unavailable_for_default_chrome_user_data'
    cdp_url = $cdpUrl
    profile_dir = $profileDir
    profile_directory = $profileDirectory
    real_profile_dir = $realProfileDir
    action = 'Use the Codex Chrome Extension to access the real user session, or configure a dedicated non-default user-data-dir for CDP automation.'
  } | ConvertTo-Json -Compress
  exit 2
}

$chromeProcesses = @(
  Get-CimInstance Win32_Process -Filter "Name = 'chrome.exe'" -ErrorAction SilentlyContinue |
    Where-Object { $_.CommandLine -and $_.CommandLine -match [regex]::Escape($profileDir) }
)

if ($chromeProcesses.Count -gt 0) {
  [pscustomobject]@{
    status = 'blocked'
    reason = 'chrome_running_without_cdp'
    cdp_url = $cdpUrl
    profile_dir = $profileDir
    profile_directory = $profileDirectory
    real_profile_dir = $realProfileDir
    action = 'Close the conflicting Chrome process or use the Codex Chrome Extension for the real user session. Agents must not launch a second default Chrome.'
    chrome_pids = @($chromeProcesses | Select-Object -ExpandProperty ProcessId)
  } | ConvertTo-Json -Compress
  exit 2
}

if (-not $LaunchIfMissing) {
  [pscustomobject]@{
    status = 'blocked'
    reason = 'chrome_not_running_or_cdp_unavailable'
    cdp_url = $cdpUrl
    profile_dir = $profileDir
    profile_directory = $profileDirectory
    real_profile_dir = $realProfileDir
    action = 'CDP is available only for a dedicated non-default automation profile. For real user tabs, use the Codex Chrome Extension.'
  } | ConvertTo-Json -Compress
  exit 2
}

$chromeCandidates = @(
  "$env:ProgramFiles\Google\Chrome\Application\chrome.exe",
  "${env:ProgramFiles(x86)}\Google\Chrome\Application\chrome.exe",
  "$env:LocalAppData\Google\Chrome\Application\chrome.exe"
) | Where-Object { $_ -and (Test-Path -LiteralPath $_) }

if (-not $chromeCandidates) {
  throw 'Google Chrome executable was not found.'
}

New-Item -ItemType Directory -Force -Path $profileDir | Out-Null

$args = @(
  '--remote-debugging-address=127.0.0.1',
  "--remote-debugging-port=$port",
  "--user-data-dir=$profileDir",
  "--profile-directory=$profileDirectory",
  '--no-first-run',
  '--new-window',
  $Url
)

$proc = Start-Process -FilePath @($chromeCandidates)[0] -ArgumentList $args -PassThru
$deadline = (Get-Date).AddSeconds([Math]::Max($TimeoutSec, 1))
do {
  if (Test-CdpReady -Endpoint $cdpUrl) {
    [pscustomobject]@{
      status = 'ready'
      cdp_url = $cdpUrl
      profile_dir = $profileDir
      profile_directory = $profileDirectory
      real_profile_dir = $realProfileDir
      launched = $true
      pid = $proc.Id
    } | ConvertTo-Json -Compress
    exit 0
  }
  Start-Sleep -Milliseconds 300
} while ((Get-Date) -lt $deadline)

throw "Shared Chrome CDP endpoint did not become ready: $cdpUrl"
