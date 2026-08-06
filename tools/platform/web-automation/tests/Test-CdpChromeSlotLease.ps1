#requires -Version 7.0
[CmdletBinding()]
param([switch]$AsJson)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$tool = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../Manage-CdpChromeSlotLease.ps1')).Path
$stateRoot = Join-Path ([IO.Path]::GetTempPath()) ("aicc-cdp-lease-test-{0}" -f [Guid]::NewGuid().ToString('N'))
$checks = [Collections.Generic.List[object]]::new()

function Add-Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $checks.Add([pscustomobject]@{ name = $Name; ok = $Ok; detail = $Detail }) | Out-Null
}

function Invoke-LeaseChild {
    param(
        [string]$Action,
        [string]$Owner = '',
        [string]$Token = '',
        [int]$Ttl = 60,
        [string]$Ports = '19222,19223'
    )
    $arguments = @(
        '-NoProfile', '-File', $tool,
        '-Action', $Action,
        '-StateRoot', $stateRoot,
        '-SlotPorts', $Ports,
        '-NoBrowser',
        '-MaxTargetsPerSlot', '3',
        '-TtlSec', [string]$Ttl,
        '-WaitSec', '0',
        '-AsJson'
    )
    if ($Owner) { $arguments += @('-OwnerId', $Owner) }
    if ($Token) { $arguments += @('-LeaseToken', $Token) }
    $output = & pwsh @arguments 2>&1
    $exitCode = $LASTEXITCODE
    $raw = $output -join "`n"
    $data = try { $raw | ConvertFrom-Json } catch { $null }
    [pscustomobject]@{ exit_code = $exitCode; raw = $raw; data = $data }
}

New-Item -ItemType Directory -Force -Path $stateRoot | Out-Null
try {
    $jobs = 1..6 | ForEach-Object {
        $sequence = $_
        $owner = if ($sequence -le 2) { 'shared-owner' } else { "owner-$sequence" }
        Start-Job -ScriptBlock {
            param($Tool, $Root, $Owner)
            & pwsh -NoProfile -File $Tool -Action Acquire -OwnerId $Owner -StateRoot $Root -SlotPorts '19222,19223' -NoBrowser -MaxTargetsPerSlot 3 -TtlSec 60 -WaitSec 2 -AsJson
        } -ArgumentList $tool, $stateRoot, $owner
    }
    $raw = @($jobs | Wait-Job | Receive-Job)
    $jobs | Remove-Job -Force
    $leases = @($raw | ForEach-Object { $_ | ConvertFrom-Json })
    Add-Check 'six parallel target acquisitions succeed' ($leases.Count -eq 6 -and @($leases | Where-Object { -not $_.ok }).Count -eq 0) ($raw -join ' | ')
    Add-Check 'least-loaded allocation fills both slots evenly' (
        @($leases | Where-Object { $_.lease.port -eq 19222 }).Count -eq 3 -and
        @($leases | Where-Object { $_.lease.port -eq 19223 }).Count -eq 3
    ) (($leases.lease.port | Sort-Object) -join ',')
    Add-Check 'every acquisition has an independent target and token' (
        @($leases.lease.target_id | Sort-Object -Unique).Count -eq 6 -and
        @($leases.lease.lease_token | Sort-Object -Unique).Count -eq 6
    ) (($leases.lease.target_id | Sort-Object) -join ',')
    Add-Check 'same owner may hold independent short action leases' (
        @($leases | Where-Object { $_.lease.owner_id -eq 'shared-owner' }).Count -eq 2
    ) (($leases.lease.owner_id | Sort-Object) -join ',')

    $fullStatus = Invoke-LeaseChild -Action Status
    Add-Check 'full status reports per-slot active count and capacity' (
        $fullStatus.exit_code -eq 0 -and
        @($fullStatus.data.slots | Where-Object { $_.status -eq 'full' -and $_.active_count -eq 3 -and $_.capacity -eq 3 }).Count -eq 2
    ) $fullStatus.raw

    $busy = Invoke-LeaseChild -Action Acquire -Owner 'owner-7'
    Add-Check 'seventh target receives bounded busy result' ($busy.exit_code -eq 3 -and $busy.data.status -eq 'busy') $busy.raw

    $first = $leases | Select-Object -First 1
    $releasedFirst = Invoke-LeaseChild -Action Release -Token ([string]$first.lease.lease_token)
    Add-Check 'individual release succeeds without releasing peers' ($releasedFirst.exit_code -eq 0 -and $releasedFirst.data.status -eq 'released') $releasedFirst.raw
    $restored = Invoke-LeaseChild -Action Acquire -Owner 'replacement-owner'
    Add-Check 'individual release restores exactly one unit of capacity' ($restored.exit_code -eq 0 -and $restored.data.ok) $restored.raw

    $heartbeat = Invoke-LeaseChild -Action Heartbeat -Token ([string]$restored.data.lease.lease_token) -Ttl 60
    Add-Check 'heartbeat renews matching target lease' ($heartbeat.exit_code -eq 0 -and $heartbeat.data.status -eq 'renewed') $heartbeat.raw

    foreach ($lease in @($leases | Where-Object { $_.lease.lease_token -ne $first.lease.lease_token })) {
        $released = Invoke-LeaseChild -Action Release -Token ([string]$lease.lease.lease_token)
        Add-Check "release closes only target $($lease.lease.target_id)" ($released.exit_code -eq 0 -and $released.data.status -eq 'released') $released.raw
    }
    $replacementRelease = Invoke-LeaseChild -Action Release -Token ([string]$restored.data.lease.lease_token)
    Add-Check 'replacement target releases cleanly' ($replacementRelease.exit_code -eq 0 -and $replacementRelease.data.status -eq 'released') $replacementRelease.raw

    $scoped = Invoke-LeaseChild -Action Acquire -Owner 'scoped-owner' -Ports '19222'
    Add-Check 'scoped lease acquired on requested slot' (
        $scoped.exit_code -eq 0 -and $scoped.data.lease.port -eq 19222
    ) $scoped.raw
    $tokenOnlyRelease = Invoke-LeaseChild -Action Release -Token ([string]$scoped.data.lease.lease_token) -Ports '19223'
    Add-Check 'token-only release ignores later allocation scope' (
        $tokenOnlyRelease.exit_code -eq 0 -and $tokenOnlyRelease.data.status -eq 'released' -and
        $tokenOnlyRelease.data.port -eq 19222
    ) $tokenOnlyRelease.raw

    $short = Invoke-LeaseChild -Action Acquire -Owner 'stale-owner' -Ttl 1
    Add-Check 'short lease acquired' ($short.exit_code -eq 0 -and $short.data.ok) $short.raw
    Start-Sleep -Milliseconds 1200
    $reclaimed = Invoke-LeaseChild -Action Acquire -Owner 'reclaimer' -Ttl 60
    Add-Check 'expired lease is reclaimed' ($reclaimed.exit_code -eq 0 -and $reclaimed.data.reclaimed_count -eq 1) $reclaimed.raw

    $reclaimedHeartbeat = Invoke-LeaseChild -Action Heartbeat -Token ([string]$reclaimed.data.lease.lease_token) -Ttl 60
    Add-Check 'heartbeat renews reclaimed token' ($reclaimedHeartbeat.exit_code -eq 0 -and $reclaimedHeartbeat.data.status -eq 'renewed') $reclaimedHeartbeat.raw
    $release = Invoke-LeaseChild -Action Release -Token ([string]$reclaimed.data.lease.lease_token)
    Add-Check 'reclaimed lease releases cleanly' ($release.exit_code -eq 0 -and $release.data.status -eq 'released') $release.raw

    $status = Invoke-LeaseChild -Action Status
    Add-Check 'all test slots return to zero active and available' (
        $status.exit_code -eq 0 -and
        @($status.data.slots | Where-Object { $_.status -ne 'available' -or $_.active_count -ne 0 -or $_.capacity -ne 3 }).Count -eq 0
    ) $status.raw
} finally {
    if (Test-Path -LiteralPath $stateRoot) { Remove-Item -LiteralPath $stateRoot -Recurse -Force }
}

$failed = @($checks | Where-Object { -not $_.ok })
$result = [ordered]@{ ok = ($failed.Count -eq 0); check_count = $checks.Count; failed_count = $failed.Count; checks = @($checks) }
if ($AsJson) { $result | ConvertTo-Json -Compress -Depth 6 } else { $result | ConvertTo-Json -Depth 6 }
if ($failed.Count) { exit 1 }
