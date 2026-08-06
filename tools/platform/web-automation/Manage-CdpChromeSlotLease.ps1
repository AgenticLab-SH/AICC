#requires -Version 7.0
<#
.SYNOPSIS
  Atomically lease a task-owned background target on a registered CDP Chrome slot.
.DESCRIPTION
  Coordinates agents without a daemon. Each port may host several independent
  target leases. A named mutex protects per-target JSON records stored outside
  the repository. Acquire chooses the least-loaded verified authenticated slot,
  starts it in background mode when necessary, and creates one background
  target. Release closes only that target.

  Port 9224 is the separate AICC-owned isolated QA browser and is intentionally
  started and stopped on demand instead of joining this authenticated pool.

  Leases cover an active browser-action interval, not an entire conversation.
  Existing tabs are never selected, activated, navigated, or closed.
#>
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('Acquire', 'Heartbeat', 'Release', 'Status')]
    [string]$Action,
    [string]$OwnerId = '',
    [string]$LeaseToken = '',
    [string]$Url = 'about:blank',
    [ValidateRange(0, 60)]
    [int]$WaitSec = 5,
    [ValidateRange(1, 86400)]
    [int]$TtlSec = 0,
    [int]$MaxTargetsPerSlot = 0,
    [string]$StateRoot = '',
    [string[]]$SlotPorts = @(),
    [string]$AccountAlias = '',
    [string]$Workspace = '',
    [string]$CoordinationPath = '',
    [switch]$NoBrowser,
    [switch]$KeepTarget,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8

$aiccStateRoot = if ($env:AICC_STATE_ROOT) { $env:AICC_STATE_ROOT } else { Join-Path $HOME '.ai-control-center' }
$coordinationPath = if ($CoordinationPath) { $CoordinationPath } elseif ($env:AICC_COORDINATION_FILE) { $env:AICC_COORDINATION_FILE } else { Join-Path $aiccStateRoot 'guidance/coordination.toml' }
$identityGuard = Join-Path $PSScriptRoot 'Assert-CdpEndpointIdentity.ps1'

function Get-TomlSection {
    param([string]$Path, [string]$Section)
    $result = @{}
    $current = ''
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if ($line -match '^\[(.+)\]$') { $current = $Matches[1]; continue }
        if ($current -ne $Section) { continue }
        if ($line -match '^([A-Za-z0-9_\-]+)\s*=\s*"([^"]*)"\s*(#.*)?$') {
            $result[$Matches[1]] = $Matches[2]
        } elseif ($line -match '^([A-Za-z0-9_\-]+)\s*=\s*([^\s#]+)\s*(#.*)?$') {
            $result[$Matches[1]] = $Matches[2]
        }
    }
    return $result
}

function Get-DefaultStateRoot {
    if ($env:AICC_CDP_LEASE_ROOT) { return $env:AICC_CDP_LEASE_ROOT }
    return (Join-Path $aiccStateRoot 'browser/cdp-target-leases')
}

$browserConfig = if (Test-Path -LiteralPath $coordinationPath -PathType Leaf) {
    Get-TomlSection -Path $coordinationPath -Section 'browser'
} else { @{} }
if ($TtlSec -eq 0) { $TtlSec = [int]$browserConfig['cdp_lease_ttl_seconds'] }
if ($TtlSec -lt 1) { $TtlSec = 600 }
if ($MaxTargetsPerSlot -eq 0) { $MaxTargetsPerSlot = [int]$browserConfig['cdp_targets_per_slot'] }
if ($MaxTargetsPerSlot -lt 1) { $MaxTargetsPerSlot = 3 }
if ($MaxTargetsPerSlot -gt 16) { throw 'MaxTargetsPerSlot must be between 1 and 16.' }

if (-not $StateRoot) { $StateRoot = Get-DefaultStateRoot }
$StateRoot = [IO.Path]::GetFullPath($StateRoot)
New-Item -ItemType Directory -Force -Path $StateRoot | Out-Null

$normalizedSlotPorts = @($SlotPorts | ForEach-Object {
    foreach ($part in ([string]$_ -split ',')) {
        $trimmed = $part.Trim()
        if (-not $trimmed) { continue }
        $parsed = 0
        if (-not [int]::TryParse($trimmed, [ref]$parsed) -or $parsed -lt 1024 -or $parsed -gt 65535) {
            throw "Invalid CDP slot port: $trimmed"
        }
        $parsed
    }
} | Sort-Object -Unique)

function Get-ConfiguredSlots {
    if ($NoBrowser -and $normalizedSlotPorts.Count -gt 0) {
        return @($normalizedSlotPorts | ForEach-Object {
            [pscustomobject]@{
                port = [int]$_
                endpoint = "http://127.0.0.1:$_"
                profile_dir = ''
                profile_directory = 'Default'
                launcher = ''
                account_alias = ''
                workspace = ''
                usage = 'test'
            }
        })
    }
    if (-not (Test-Path -LiteralPath $coordinationPath -PathType Leaf)) {
        throw "coordination.toml not found: $coordinationPath"
    }
    $count = [int]$browserConfig['cdp_slot_count']
    if ($count -lt 1) { throw 'No registered CDP Chrome slots are configured.' }
    $configured = for ($index = 1; $index -le $count; $index++) {
        $port = [int]$browserConfig["cdp_slot${index}_port"]
        if ($normalizedSlotPorts.Count -gt 0 -and $port -notin $normalizedSlotPorts) { continue }
        $profile = [string]$browserConfig["cdp_slot${index}_profile_dir"]
        if (-not $port -or -not $profile) { throw "Incomplete CDP slot configuration at index $index." }
        $launcher = [string]$browserConfig["cdp_slot${index}_launcher"]
        [pscustomobject]@{
            port = $port
            endpoint = "http://127.0.0.1:$port"
            profile_dir = $profile
            profile_directory = [string]$browserConfig["cdp_slot${index}_profile_directory"]
            launcher = $launcher
            account_alias = [string]$browserConfig["cdp_slot${index}_account_alias"]
            workspace = [string]$browserConfig["cdp_slot${index}_workspace"]
            usage = [string]$browserConfig["cdp_slot${index}_usage"]
        }
    }
    if ($AccountAlias) {
        $configured = @($configured | Where-Object {
            $_.account_alias -eq $AccountAlias -and (-not $Workspace -or $_.workspace -eq $Workspace)
        })
    }
    $resolved = @($configured | Sort-Object port)
    if ($resolved.Count -eq 0) {
        $requestedIdentity = if ($AccountAlias) { "$AccountAlias/$Workspace" } else { 'registered authenticated slots' }
        throw "No registered CDP Chrome slots matched the requested scope: $requestedIdentity"
    }
    return $resolved
}

$slots = @(Get-ConfiguredSlots)
if (-not $OwnerId) {
    $OwnerId = @($env:CODEX_THREAD_ID, $env:CLAUDE_SESSION_ID, $env:AGENT_TASK_ID) |
        Where-Object { $_ } | Select-Object -First 1
}
if (-not $OwnerId) { $OwnerId = "manual-$([Guid]::NewGuid().ToString('N'))" }

$hashBytes = [Security.Cryptography.SHA256]::HashData([Text.Encoding]::UTF8.GetBytes($StateRoot))
$mutexSuffix = ([Convert]::ToHexString($hashBytes)).Substring(0, 20)
$mutex = [Threading.Mutex]::new($false, "AICC.CdpChromeTargetLease.$mutexSuffix")

function Enter-LeaseMutex {
    try {
        if (-not $mutex.WaitOne([TimeSpan]::FromSeconds(15))) { throw 'Timed out waiting for the CDP target lease mutex.' }
    } catch [Threading.AbandonedMutexException] { }
}
function Exit-LeaseMutex { try { $mutex.ReleaseMutex() } catch { } }

function Get-PortLeaseDirectory {
    param([int]$Port)
    Join-Path $StateRoot ("{0}.leases" -f $Port)
}
function Get-LeasePath {
    param([int]$Port, [string]$Token)
    Join-Path (Get-PortLeaseDirectory -Port $Port) ("{0}.lease.json" -f $Token)
}
function Read-PortLeases {
    param([int]$Port)
    $dir = Get-PortLeaseDirectory -Port $Port
    if (-not (Test-Path -LiteralPath $dir -PathType Container)) { return @() }
    $records = foreach ($path in Get-ChildItem -LiteralPath $dir -Filter '*.lease.json' -File -ErrorAction SilentlyContinue) {
        try { Get-Content -LiteralPath $path.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } catch { }
    }
    return @($records)
}
function Write-Lease {
    param([Parameter(Mandatory)]$Lease)
    $dir = Get-PortLeaseDirectory -Port ([int]$Lease.port)
    New-Item -ItemType Directory -Force -Path $dir | Out-Null
    $path = Get-LeasePath -Port ([int]$Lease.port) -Token ([string]$Lease.lease_token)
    $temp = Join-Path $dir ("{0}.{1}.tmp" -f $Lease.lease_token, [Guid]::NewGuid().ToString('N'))
    [IO.File]::WriteAllText($temp, ($Lease | ConvertTo-Json -Depth 7) + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
    Move-Item -LiteralPath $temp -Destination $path -Force
}
function Remove-LeaseRecord {
    param($Lease)
    $path = Get-LeasePath -Port ([int]$Lease.port) -Token ([string]$Lease.lease_token)
    Remove-Item -LiteralPath $path -Force -ErrorAction SilentlyContinue
    if ($Lease.control_state_dir -and (Test-Path -LiteralPath ([string]$Lease.control_state_dir) -PathType Container)) {
        Remove-Item -LiteralPath ([string]$Lease.control_state_dir) -Recurse -Force -ErrorAction SilentlyContinue
    }
}
function Test-LeaseExpired {
    param($Lease)
    if ($null -eq $Lease -or -not $Lease.expires_at_utc) { return $true }
    try { return [DateTimeOffset]::Parse([string]$Lease.expires_at_utc) -le [DateTimeOffset]::UtcNow } catch { return $true }
}
function New-LeaseRecord {
    param($Slot)
    $now = [DateTimeOffset]::UtcNow
    $token = [Guid]::NewGuid().ToString('N')
    [pscustomobject][ordered]@{
        schema_version = 2
        state = 'provisioning'
        owner_id = $OwnerId
        lease_token = $token
        port = [int]$Slot.port
        endpoint = [string]$Slot.endpoint
        profile_dir = [string]$Slot.profile_dir
        profile_directory = if ($Slot.profile_directory) { [string]$Slot.profile_directory } else { 'Default' }
        account_alias = [string]$Slot.account_alias
        workspace = [string]$Slot.workspace
        acquired_at_utc = $now.ToString('o')
        heartbeat_at_utc = $now.ToString('o')
        expires_at_utc = $now.AddSeconds($TtlSec).ToString('o')
        ttl_seconds = $TtlSec
        target_id = $null
        target_url = $null
        control_state_dir = Join-Path (Get-PortLeaseDirectory -Port ([int]$Slot.port)) ("control-{0}" -f $token)
        browser_started_by_lease = $false
    }
}
function Update-LeaseHeartbeat {
    param($Lease)
    $now = [DateTimeOffset]::UtcNow
    $Lease.heartbeat_at_utc = $now.ToString('o')
    $Lease.expires_at_utc = $now.AddSeconds($TtlSec).ToString('o')
    $Lease.ttl_seconds = $TtlSec
    Write-Lease -Lease $Lease
    return $Lease
}
function Find-LeaseByToken {
    param([string]$Token)
    # A lease token is the complete capability for heartbeat/release. Do not
    # reapply the Acquire scope here: an account-routed slot must still be
    # releasable by token alone in a later process invocation.
    foreach ($path in Get-ChildItem -LiteralPath $StateRoot -Filter '*.lease.json' -File -Recurse -ErrorAction SilentlyContinue) {
        $lease = try { Get-Content -LiteralPath $path.FullName -Raw -Encoding UTF8 | ConvertFrom-Json } catch { $null }
        if ($lease -and [string]$lease.lease_token -eq $Token) { return $lease }
    }
    return $null
}

function Get-IdentityReport {
    param($Slot)
    $raw = @(& pwsh -NoProfile -File $identityGuard -ExpectedBrowser chrome -Endpoint $Slot.endpoint -ExpectedProfileDir $Slot.profile_dir -AsJson 2>$null) -join "`n"
    $exitCode = $LASTEXITCODE
    $report = try { $raw | ConvertFrom-Json } catch { $null }
    [pscustomobject]@{ exit_code = $exitCode; report = $report; raw = $raw }
}
function Start-RegisteredSlot {
    param($Slot)
    if (-not $Slot.launcher -or -not (Test-Path -LiteralPath $Slot.launcher)) {
        throw "Registered launcher is missing for CDP Chrome $($Slot.port): $($Slot.launcher)"
    }
    if ($IsMacOS) {
        & /usr/bin/open -gj --env 'AICC_BACKGROUND_LAUNCH=1' $Slot.launcher
        if ($LASTEXITCODE -ne 0) { throw "Failed to open registered launcher in background: $($Slot.launcher)" }
    } elseif ($IsWindows) {
        Start-Process -FilePath $Slot.launcher -WindowStyle Minimized | Out-Null
    } else { throw 'Automatic registered-slot launch is supported only on macOS and Windows.' }
}
function Ensure-SlotReady {
    param($Slot)
    if ($NoBrowser) { return $false }
    $identity = Get-IdentityReport -Slot $Slot
    if ($identity.exit_code -eq 0 -and $identity.report.ok) { return $false }
    $reasons = @($identity.report.reasons)
    $unavailableOnly = $reasons.Count -gt 0 -and @($reasons | Where-Object { $_ -ne 'cdp_endpoint_unavailable' }).Count -eq 0
    if (-not $unavailableOnly) { throw "CDP Chrome $($Slot.port) identity mismatch; refusing fallback: $($identity.raw)" }
    Start-RegisteredSlot -Slot $Slot
    $deadline = [DateTimeOffset]::UtcNow.AddSeconds(20)
    do {
        Start-Sleep -Milliseconds 250
        $identity = Get-IdentityReport -Slot $Slot
        if ($identity.exit_code -eq 0 -and $identity.report.ok) { return $true }
    } while ([DateTimeOffset]::UtcNow -lt $deadline)
    throw "Registered CDP Chrome $($Slot.port) did not pass identity verification after background launch: $($identity.raw)"
}
function Get-CdpTargets {
    param([string]$Endpoint, [switch]$Strict)
    if ($NoBrowser) { return @() }
    try {
        $response = Invoke-RestMethod -Uri ($Endpoint.TrimEnd('/') + '/json/list') -TimeoutSec 3
        foreach ($target in $response) { Write-Output $target }
    } catch { if ($Strict) { throw }; return @() }
}
function Invoke-CdpBrowserCommand {
    param([string]$Endpoint, [string]$Method, [hashtable]$Params = @{})
    $version = Invoke-RestMethod -Uri ($Endpoint.TrimEnd('/') + '/json/version') -TimeoutSec 3
    if (-not $version.webSocketDebuggerUrl) { throw "CDP browser websocket was not advertised by $Endpoint." }
    $socket = [Net.WebSockets.ClientWebSocket]::new()
    try {
        $cts = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
        try { $null = $socket.ConnectAsync([Uri]$version.webSocketDebuggerUrl, $cts.Token).GetAwaiter().GetResult() } finally { $cts.Dispose() }
        $id = [Security.Cryptography.RandomNumberGenerator]::GetInt32(1, [int]::MaxValue)
        $payload = [Text.Encoding]::UTF8.GetBytes((@{ id = $id; method = $Method; params = $Params } | ConvertTo-Json -Compress -Depth 8))
        $cts = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
        try { $null = $socket.SendAsync([ArraySegment[byte]]::new($payload), [Net.WebSockets.WebSocketMessageType]::Text, $true, $cts.Token).GetAwaiter().GetResult() } finally { $cts.Dispose() }
        do {
            $stream = [IO.MemoryStream]::new()
            $cts = [Threading.CancellationTokenSource]::new([TimeSpan]::FromSeconds(5))
            try {
                do {
                    $buffer = [byte[]]::new(16384)
                    $received = $socket.ReceiveAsync([ArraySegment[byte]]::new($buffer), $cts.Token).GetAwaiter().GetResult()
                    if ($received.MessageType -eq [Net.WebSockets.WebSocketMessageType]::Close) { throw "CDP websocket closed before replying to $Method." }
                    $stream.Write($buffer, 0, $received.Count)
                } while (-not $received.EndOfMessage)
                $message = [Text.Encoding]::UTF8.GetString($stream.ToArray()) | ConvertFrom-Json
            } finally { $cts.Dispose(); $stream.Dispose() }
        } while ([long]$message.id -ne $id)
        if ($message.error) { throw "CDP $Method failed: $($message.error | ConvertTo-Json -Compress)" }
        return $message.result
    } finally { $socket.Dispose() }
}
function New-OwnedTarget {
    param($Slot)
    if ($NoBrowser) { return "synthetic-$([Guid]::NewGuid().ToString('N'))" }
    $target = Invoke-CdpBrowserCommand -Endpoint $Slot.endpoint -Method 'Target.createTarget' -Params @{ url = $Url; background = $true }
    if (-not $target.targetId) { throw "CDP Chrome $($Slot.port) did not return a target ID." }
    return [string]$target.targetId
}
function Write-ControlState {
    param($Lease)
    if ($NoBrowser -or -not $Lease.control_state_dir -or -not $Lease.target_id) { return }
    New-Item -ItemType Directory -Force -Path ([string]$Lease.control_state_dir) | Out-Null
    $state = [ordered]@{ port = [int]$Lease.port; activeTargetId = [string]$Lease.target_id; managed_by = 'AICC.CdpChromeTargetLease' }
    [IO.File]::WriteAllText((Join-Path ([string]$Lease.control_state_dir) 'browser-state.json'), ($state | ConvertTo-Json) + [Environment]::NewLine, [Text.UTF8Encoding]::new($false))
}
function Close-OwnedTarget {
    param($Lease)
    if ($NoBrowser -or $KeepTarget -or -not $Lease -or -not $Lease.target_id) { return $false }
    $targets = @(Get-CdpTargets -Endpoint ([string]$Lease.endpoint) -Strict)
    if (@($targets | Where-Object { [string]$_.id -eq [string]$Lease.target_id }).Count -eq 0) { return $true }
    try {
        $closeUri = ([string]$Lease.endpoint).TrimEnd('/') + "/json/close/$($Lease.target_id)"
        Invoke-RestMethod -Uri $closeUri -TimeoutSec 3 | Out-Null
        $deadline = [DateTimeOffset]::UtcNow.AddSeconds(8)
        $absentSince = $null
        $lastCloseAt = [DateTimeOffset]::UtcNow
        do {
            Start-Sleep -Milliseconds 200
            $remaining = @(Get-CdpTargets -Endpoint ([string]$Lease.endpoint) -Strict | Where-Object { [string]$_.id -eq [string]$Lease.target_id })
            if ($remaining.Count -eq 0) {
                if ($null -eq $absentSince) { $absentSince = [DateTimeOffset]::UtcNow }
                if ([DateTimeOffset]::UtcNow - $absentSince -ge [TimeSpan]::FromMilliseconds(1500)) { return $true }
            } else {
                $absentSince = $null
                if ([DateTimeOffset]::UtcNow - $lastCloseAt -ge [TimeSpan]::FromSeconds(1)) {
                    Invoke-RestMethod -Uri $closeUri -TimeoutSec 3 | Out-Null
                    $lastCloseAt = [DateTimeOffset]::UtcNow
                }
            }
        } while ([DateTimeOffset]::UtcNow -lt $deadline)
    } catch { }
    return $false
}
function Write-Result {
    param($Result, [int]$ExitCode = 0)
    if ($AsJson) { $Result | ConvertTo-Json -Compress -Depth 8 } else { $Result | ConvertTo-Json -Depth 8 }
    $mutex.Dispose()
    exit $ExitCode
}

if ($Action -eq 'Status') {
    $records = foreach ($slot in $slots) {
        $leases = @(Read-PortLeases -Port $slot.port)
        $active = @($leases | Where-Object { -not (Test-LeaseExpired $_) -and [string]$_.state -notin @('releasing', 'cleanup_failed') })
        [pscustomobject]@{
            port = $slot.port
            endpoint = $slot.endpoint
            status = if ($active.Count -ge $MaxTargetsPerSlot) { 'full' } elseif ($active.Count -gt 0) { 'shared' } else { 'available' }
            active_count = $active.Count
            capacity = $MaxTargetsPerSlot
            leases = @($active | ForEach-Object { [pscustomobject]@{ owner_id = $_.owner_id; expires_at_utc = $_.expires_at_utc; target_id = $_.target_id; state = $_.state } })
        }
    }
    Write-Result ([pscustomobject]@{ ok = $true; state_root = $StateRoot; slots = @($records) })
}

if ($Action -in @('Heartbeat', 'Release')) {
    if (-not $LeaseToken) { throw "-$Action requires -LeaseToken." }
    Enter-LeaseMutex
    try {
        $matched = Find-LeaseByToken -Token $LeaseToken
        if (-not $matched) { throw 'Lease token was not found.' }
        if ($Action -eq 'Heartbeat') { $matched = Update-LeaseHeartbeat -Lease $matched }
        else { $matched.state = 'releasing'; $matched = Update-LeaseHeartbeat -Lease $matched }
    } finally { Exit-LeaseMutex }
    if ($Action -eq 'Heartbeat') { Write-Result ([pscustomobject]@{ ok = $true; status = 'renewed'; lease = $matched }) }
    $closed = Close-OwnedTarget -Lease $matched
    $released = $closed -or $NoBrowser -or $KeepTarget
    if ($released) {
        Enter-LeaseMutex
        try {
            $current = Find-LeaseByToken -Token $LeaseToken
            if ($current) { Remove-LeaseRecord -Lease $current }
        } finally { Exit-LeaseMutex }
    }
    Write-Result ([pscustomobject]@{ ok = $released; status = if ($released) { 'released' } else { 'release_pending_cleanup' }; port = [int]$matched.port; target_id = $matched.target_id; target_closed = $closed }) $(if ($released) { 0 } else { 4 })
}

$deadline = [DateTimeOffset]::UtcNow.AddSeconds($WaitSec)
$selected = $null
$reclaimed = @()
do {
    $expired = @()
    Enter-LeaseMutex
    try {
        foreach ($slot in $slots) {
            foreach ($lease in @(Read-PortLeases -Port $slot.port)) {
                if ((Test-LeaseExpired $lease) -and [string]$lease.state -ne 'reclaiming') {
                    $lease.state = 'reclaiming'; Write-Lease $lease; $expired += $lease
                }
            }
        }
    } finally { Exit-LeaseMutex }
    foreach ($lease in $expired) {
        $closed = Close-OwnedTarget $lease
        if ($closed -or $NoBrowser -or $KeepTarget) {
            Enter-LeaseMutex
            try { $current = Find-LeaseByToken $lease.lease_token; if ($current) { Remove-LeaseRecord $current; $reclaimed += $lease } } finally { Exit-LeaseMutex }
        } else {
            Enter-LeaseMutex
            try { $current = Find-LeaseByToken $lease.lease_token; if ($current) { $current.state = 'cleanup_failed'; Write-Lease $current } } finally { Exit-LeaseMutex }
        }
    }

    Enter-LeaseMutex
    try {
        $candidates = foreach ($slot in $slots) {
            $active = @(Read-PortLeases -Port $slot.port | Where-Object { -not (Test-LeaseExpired $_) -and [string]$_.state -notin @('releasing', 'cleanup_failed') })
            if ($active.Count -lt $MaxTargetsPerSlot) { [pscustomobject]@{ slot = $slot; count = $active.Count } }
        }
        $choice = $candidates | Sort-Object count, @{ Expression = { $_.slot.port } } | Select-Object -First 1
        if ($choice) {
            $record = New-LeaseRecord -Slot $choice.slot
            Write-Lease -Lease $record
            $selected = [pscustomobject]@{ slot = $choice.slot; lease = $record }
        }
    } finally { Exit-LeaseMutex }
    if ($selected -or [DateTimeOffset]::UtcNow -ge $deadline) { break }
    Start-Sleep -Milliseconds 250
} while ($true)

if (-not $selected) {
    $busy = foreach ($slot in $slots) {
        $active = @(Read-PortLeases -Port $slot.port | Where-Object { -not (Test-LeaseExpired $_) })
        [pscustomobject]@{ port = $slot.port; active_count = $active.Count; capacity = $MaxTargetsPerSlot }
    }
    Write-Result ([pscustomobject]@{ ok = $false; status = 'busy'; reason = 'all_registered_cdp_chrome_target_capacity_is_leased'; slots = @($busy) }) 3
}

$createdTarget = $null
try {
    $started = Ensure-SlotReady -Slot $selected.slot
    $lease = $selected.lease
    $createdTarget = New-OwnedTarget -Slot $selected.slot
    $lease.target_id = $createdTarget
    $lease.target_url = $Url
    Write-ControlState -Lease $lease
    $lease.state = 'ready'
    $lease.browser_started_by_lease = [bool]$started
    Enter-LeaseMutex
    try {
        $current = Find-LeaseByToken $lease.lease_token
        if (-not $current) { throw 'Lease ownership changed while the target was being prepared.' }
        $lease = Update-LeaseHeartbeat -Lease $lease
    } finally { Exit-LeaseMutex }
    Write-Result ([pscustomobject]@{
        ok = $true
        status = 'acquired'
        lease = $lease
        reclaimed_count = $reclaimed.Count
        instructions = 'Use only target_id with BROWSER_AGENT_HOME=control_state_dir. Never activate the target. Release immediately after this browser-action interval.'
    })
} catch {
    if ($createdTarget) { $selected.lease.target_id = $createdTarget; Close-OwnedTarget $selected.lease | Out-Null }
    Enter-LeaseMutex
    try { $current = Find-LeaseByToken $selected.lease.lease_token; if ($current) { Remove-LeaseRecord $current } } finally { Exit-LeaseMutex }
    throw
}
