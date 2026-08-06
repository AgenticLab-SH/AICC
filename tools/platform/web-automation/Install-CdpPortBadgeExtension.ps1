[CmdletBinding()]
param(
    [string]$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path,
    [string[]]$OnlySlots = @(),
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
if (-not ($IsMacOS -or $IsWindows)) {
    throw 'This installer supports the registered macOS and Windows CDP browser slots.'
}

$extensionPath = Join-Path $AiccRoot 'tools/platform/web-automation/extensions/aicc-cdp-port-badge'
$nodeInstaller = Join-Path $AiccRoot 'tools/platform/web-automation/install-cdp-port-badge-extension.mjs'
$identityGuard = Join-Path $AiccRoot 'tools/platform/web-automation/Assert-CdpEndpointIdentity.ps1'
foreach ($required in @($extensionPath, $nodeInstaller, $identityGuard)) {
    if (-not (Test-Path -LiteralPath $required)) { throw "Required CDP badge component is missing: $required" }
}

# Slot profile roots differ per device family. Resolve them from the running
# platform instead of hardcoding one host's layout, so the same repo checkout
# works on macOS and Windows.
$userHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)
if (-not $userHome) { $userHome = $HOME }
if ($IsWindows) {
    $localAppData = [Environment]::GetFolderPath([Environment+SpecialFolder]::LocalApplicationData)
    if (-not $localAppData) { $localAppData = Join-Path $userHome 'AppData\Local' }
    $chromeSlotRoot = Join-Path $localAppData 'Google'
    $slots = @(
        [ordered]@{slot='9222';browser='chrome';endpoint='http://127.0.0.1:9222';profile=(Join-Path $chromeSlotRoot 'Chrome-CDP\UserData');profile_directory='Default'},
        [ordered]@{slot='9223';browser='chrome';endpoint='http://127.0.0.1:9223';profile=(Join-Path $chromeSlotRoot 'Chrome-CDP-9223\UserData');profile_directory='Default'},
        [ordered]@{slot='9335';browser='whale';endpoint='http://127.0.0.1:9335';profile=(Join-Path $localAppData 'Naver\Whale-CDP\UserData');profile_directory='Profile 1'}
    )
} else {
    $aiccState = Join-Path $userHome '.ai-control-center/browser-profiles'
    $slots = @(
        [ordered]@{slot='9222';browser='chrome';endpoint='http://127.0.0.1:9222';profile=(Join-Path $aiccState 'chrome/9222/UserData');profile_directory='Default'},
        [ordered]@{slot='9223';browser='chrome';endpoint='http://127.0.0.1:9223';profile=(Join-Path $aiccState 'chrome/9223/UserData');profile_directory='Default'},
        [ordered]@{slot='9335';browser='whale';endpoint='http://127.0.0.1:9335';profile=(Join-Path $aiccState 'whale/9335/UserData');profile_directory='Profile 1'}
    )
}
if ($OnlySlots.Count -gt 0) {
    $slots = @($slots | Where-Object { $_.slot -in $OnlySlots })
    if ($slots.Count -eq 0) { throw "No registered slots matched: $($OnlySlots -join ', ')" }
}

$results = @()
foreach ($slot in $slots) {
    $guardArguments = @(
        '-NoLogo', '-NoProfile', '-File', $identityGuard,
        '-Endpoint', $slot.endpoint,
        '-ExpectedBrowser', $slot.browser,
        '-ExpectedProfileDir', $slot.profile,
        '-AsJson'
    )
    $guardOutput = & pwsh @guardArguments | Out-String
    if ($LASTEXITCODE -ne 0) { throw "CDP identity guard failed for slot $($slot.slot): $guardOutput" }
    $guard = $guardOutput | ConvertFrom-Json
    if (-not $guard.ok) { throw "CDP identity guard rejected slot $($slot.slot)." }

    $installOutput = & node $nodeInstaller --endpoint $slot.endpoint --extension $extensionPath --slot $slot.slot | Out-String
    if ($LASTEXITCODE -ne 0) { throw "CDP badge installation failed for slot $($slot.slot): $installOutput" }
    $installed = $installOutput | ConvertFrom-Json
    $results += [ordered]@{
        slot = $slot.slot
        browser = $slot.browser
        endpoint = $slot.endpoint
        profile = $slot.profile
        profile_directory = $slot.profile_directory
        extension_id = $installed.extension_id
        extension_path = $installed.extension_path
        enabled = [bool]$installed.enabled
        toolbar_pinned = [bool]$installed.toolbar_pinned
        badge = [string]$installed.badge
        title = [string]$installed.title
        identity_verified = [bool]$guard.ok
        badge_status = if ($installed.status) { [string]$installed.status } else { 'installed' }
        badge_supported = ([string]$installed.status -ne 'unsupported')
        badge_reason = if ($installed.reason) { [string]$installed.reason } else { $null }
    }
}

$report = [ordered]@{
    ok = $true
    extension = $extensionPath
    permission_model = 'storage_only_no_host_permissions_no_content_scripts'
    note = 'Whale builds without Extensions.loadUnpacked report badge_status=unsupported; endpoint, process, port, and profile identity verification remains mandatory.'
    slots = $results
}
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 6 } else { $report | ConvertTo-Json -Depth 6 }
