#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('chrome', 'whale')]
    [string]$ExpectedBrowser,
    [string]$Endpoint = '',
    [string]$ExpectedProfileDir = '',
    [string]$CoordinationPath = '',
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if ([string]::IsNullOrWhiteSpace($Endpoint) -or [string]::IsNullOrWhiteSpace($ExpectedProfileDir)) {
    throw 'Pass -Endpoint and -ExpectedProfileDir explicitly from the selected private coordination entry.'
}

try {
    $uri = [Uri]$Endpoint
} catch {
    throw "Invalid CDP endpoint: $Endpoint"
}
if ($uri.Scheme -ne 'http' -or $uri.Host -notin @('127.0.0.1', 'localhost', '::1')) {
    throw "Only loopback HTTP CDP endpoints are allowed: $Endpoint"
}

$port = [int]$uri.Port
$expectedProcess = if ($ExpectedBrowser -eq 'whale') { 'whale' } else { 'chrome' }
$reasons = [System.Collections.Generic.List[string]]::new()
$version = $null
$listener = $null
$process = $null

try {
    $version = Invoke-RestMethod -Uri ($Endpoint.TrimEnd('/') + '/json/version') -TimeoutSec 3
} catch {
    $reasons.Add('cdp_endpoint_unavailable') | Out-Null
}

if ($null -ne $version) {
    if ($IsWindows) {
        $listener = Get-NetTCPConnection -State Listen -LocalPort $port -ErrorAction SilentlyContinue |
            Where-Object { $_.LocalAddress -in @('127.0.0.1', '::1', '0.0.0.0', '::') } |
            Select-Object -First 1
    } else {
        $listenerPid = @(& /usr/sbin/lsof -nP "-iTCP:$port" -sTCP:LISTEN -t 2>$null) |
            Select-Object -First 1
        if ($listenerPid) {
            $listener = [pscustomobject]@{ OwningProcess = [int]$listenerPid }
        }
    }
    if ($null -eq $listener) {
        $reasons.Add('listener_not_found') | Out-Null
    } else {
        if ($IsWindows) {
            $process = Get-CimInstance Win32_Process -Filter "ProcessId=$($listener.OwningProcess)" -ErrorAction SilentlyContinue
        } else {
            $pidText = [string]$listener.OwningProcess
            $commandText = (& /bin/ps -p $pidText -o command= 2>$null | Out-String).Trim()
            $executableText = (& /bin/ps -p $pidText -o comm= 2>$null | Out-String).Trim()
            if ($commandText) {
                $process = [pscustomobject]@{
                    Name = [IO.Path]::GetFileName($executableText)
                    CommandLine = $commandText
                    ExecutablePath = $executableText
                }
            }
        }
        if ($null -eq $process) {
            $reasons.Add('listener_process_not_found') | Out-Null
        }
    }
}

$processName = if ($process) { [string]$process.Name } else { '' }
$commandLine = if ($process) { [string]$process.CommandLine } else { '' }
$processMatches = if (-not $process) {
    $false
} elseif ($IsWindows) {
    [string]::Equals(
        $processName,
        ($expectedProcess + '.exe'),
        [StringComparison]::OrdinalIgnoreCase
    )
} elseif ($ExpectedBrowser -eq 'whale') {
    $commandLine -match '(?i)(^|/)(Whale|Whale\.real)(\s|$)' -and
        $commandLine -notmatch '(?i)Google Chrome'
} else {
    $commandLine -match '(?i)(Google Chrome|chrome)( for Testing)?(\.real)?(\s|$)' -and
        $commandLine -notmatch '(?i)(^|/)(Whale|Whale\.real)(\s|$)'
}
if ($process -and -not $processMatches) {
    $reasons.Add('wrong_browser_process') | Out-Null
}

$portMatches = $process -and $commandLine -match ("--remote-debugging-port={0}(\s|$)" -f $port)
if ($process -and -not $portMatches) {
    $reasons.Add('debug_port_not_owned_by_process') | Out-Null
}

$normalizedProfile = if ($IsWindows) {
    $ExpectedProfileDir.Trim() -replace '/', '\'
} else {
    $ExpectedProfileDir.Trim() -replace '\\', '/'
}
$profileMatches = $false
if ($process -and -not [string]::IsNullOrWhiteSpace($normalizedProfile)) {
    $profileMatches = $commandLine -match [regex]::Escape($normalizedProfile)
    if (-not $profileMatches) {
        $reasons.Add('wrong_browser_profile') | Out-Null
    }
} elseif ($process) {
    $reasons.Add('expected_profile_missing') | Out-Null
}

$ok = $reasons.Count -eq 0
$result = [ordered]@{
    ok = $ok
    expected_browser = $ExpectedBrowser
    endpoint = $Endpoint
    port = $port
    cdp_product = if ($version) { [string]$version.Browser } else { $null }
    listener_pid = if ($listener) { [int]$listener.OwningProcess } else { $null }
    process_name = if ($process) { $processName } else { $null }
    executable_path = if ($process) { [string]$process.ExecutablePath } else { $null }
    expected_process_name = $expectedProcess
    process_matches = [bool]$processMatches
    port_matches = [bool]$portMatches
    expected_profile_dir = $normalizedProfile
    profile_matches = [bool]$profileMatches
    reasons = @($reasons)
    note = 'CDP product strings are not browser identity: Whale may report Chrome. The listener process and profile are authoritative.'
}

$json = $result | ConvertTo-Json -Compress -Depth 5
if ($AsJson) {
    $json
} else {
    $result | ConvertTo-Json -Depth 5
}
if (-not $ok) {
    exit 2
}
