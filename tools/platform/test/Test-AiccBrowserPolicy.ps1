#requires -Version 7.0
[CmdletBinding()]
param(
    [string]$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path,
    [string]$CoordinationPath = (Join-Path $HOME '.ai-control-center/guidance/coordination.toml'),
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
$checks = [Collections.Generic.List[object]]::new()
function Add-Check([string]$Name, [bool]$Ok, [string]$Detail = '') {
    $checks.Add([pscustomobject]@{ name=$Name; ok=$Ok; detail=$Detail }) | Out-Null
}
function Read-Text([string]$RelativePath) {
    $path = Join-Path $AiccRoot $RelativePath
    if (-not (Test-Path -LiteralPath $path -PathType Leaf)) { return '' }
    Get-Content -LiteralPath $path -Raw -Encoding UTF8
}
function Read-TomlValue([string]$Path, [string]$Section, [string]$Key) {
    $current = ''
    foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
        $line = $raw.Trim()
        if ($line -match '^\[(?<name>[^\]]+)\]$') { $current = $Matches.name; continue }
        if ($current -eq $Section -and $line -match ('^' + [regex]::Escape($Key) + '\s*=\s*"(?<value>[^"]*)"')) { return $Matches.value }
    }
    return ''
}

$macInstaller = Read-Text 'tools/platform/web-automation/Install-SeparatedBrowserAppsOnMac.ps1'
$whaleInstaller = Read-Text 'tools/platform/web-automation/Install-ImportedBrowserAppsOnMac.ps1'
$whaleLauncher = Read-Text 'tools/platform/web-automation/macos/CdpWhaleLauncher.swift'
$statusLauncher = Read-Text 'tools/platform/web-automation/macos/CdpChromeStatusLauncher.swift'
$normalChromeLauncher = Read-Text 'tools/platform/web-automation/macos/NormalChromeLauncher.swift'
$normalWhaleLauncher = Read-Text 'tools/platform/web-automation/macos/NormalWhaleLauncher.swift'
$badgeInstaller = Read-Text 'tools/platform/web-automation/Install-CdpPortBadgeExtension.ps1'
$identityGuard = Read-Text 'tools/platform/web-automation/Assert-CdpEndpointIdentity.ps1'
$windowsInstaller = Read-Text 'tools/platform/web-automation/Install-SeparatedBrowserAppsOnWindows.ps1'
$windowsChrome = Read-Text 'tools/platform/web-automation/windows/CDPChromeLauncher.cs'
$windowsWhale = Read-Text 'tools/platform/web-automation/windows/CDPWhaleLauncher.cs'
$lease = Read-Text 'tools/platform/web-automation/Manage-CdpChromeSlotLease.ps1'
$extensionRoot = Join-Path $AiccRoot 'tools/platform/web-automation/extensions/aicc-cdp-port-badge'

Add-Check 'mac launchers use private AICC profile roots' (
    $macInstaller -match '\.ai-control-center/browser-profiles/chrome/9222/UserData' -and
    $macInstaller -match '\.ai-control-center/browser-profiles/chrome/9223/UserData' -and
    $whaleLauncher -match '\.ai-control-center/browser-profiles/whale/9335/UserData'
) 'macOS profile defaults'
Add-Check 'mac launchers use AICC bundle and plist identity' (
    $macInstaller -match 'com\.aicc\.chrome\.cdp\.9222' -and
    $macInstaller -match 'com\.aicc\.chrome\.cdp\.9223' -and
    $whaleInstaller -match 'com\.aicc\.whale\.cdp\.9335' -and
    $macInstaller -match "Key 'AICCUserData'" -and
    $statusLauncher -match 'AICC\.CdpChromeStatusLauncher'
) 'bundle and plist identity'
Add-Check 'normal Chrome and Whale use distinct non-CDP controllers' (
    $macInstaller -match 'com\.aicc\.chrome\.normal' -and
    $macInstaller -match 'com\.aicc\.whale\.normal' -and
    $macInstaller -match 'Library/Application Support/Google/Chrome' -and
    $macInstaller -match 'Library/Application Support/Naver/Whale' -and
    $normalChromeLauncher -match '!command\.contains\("--remote-debugging-port="\)' -and
    $normalWhaleLauncher -match '!command\.contains\("--remote-debugging-port="\)' -and
    $normalWhaleLauncher -match 'runningApplications\(withBundleIdentifier: "com\.naver\.Whale"\)' -and
    $normalWhaleLauncher -match 'finishLaunchVerification\(attempt:'
) 'ordinary profiles remain separate from registered CDP slots'
Add-Check 'Dock opens normal Whale through its exact controller' (
    $macInstaller -match "name='NAVER Whale \(일반\)';bundle='com\.aicc\.whale\.normal'" -and
    $macInstaller -notmatch "name='NAVER Whale';bundle='com\.naver\.Whale';path='/Applications/Whale\.app'" -and
    $normalWhaleLauncher -match 'NSWorkspace\.didLaunchApplicationNotification' -and
    $normalWhaleLauncher -match 'NSWorkspace\.didTerminateApplicationNotification' -and
    $normalWhaleLauncher -notmatch 'Timer\.scheduledTimer'
) 'prevents vendor bundle activation from selecting CDP Whale 9335'
Add-Check 'Whale launcher keeps vendor engine unchanged' (
    $whaleInstaller -match '/Applications/Whale\.app/Contents/MacOS/Whale' -and
    $whaleInstaller -match 'persistent-status-web-handler-vendor-browser-launcher' -and
    $whaleLauncher -match '/Applications/Whale\.app/Contents/MacOS/Whale' -and
    $whaleLauncher -match 'WHALE_CDP_USER_DATA_DIR' -and
    $whaleInstaller -notmatch '/usr/bin/ditto \$sourceApp \$app' -and
    $whaleInstaller -notmatch 'Whale\.real'
) 'lightweight launcher invokes unchanged vendor executable'
Add-Check 'Whale launcher receives web links and HTML documents' (
    $whaleInstaller -match 'CFBundleURLTypes' -and
    $whaleInstaller -match 'CFBundleURLSchemes:0 string http' -and
    $whaleInstaller -match 'CFBundleURLSchemes:1 string https' -and
    $whaleInstaller -match 'CFBundleDocumentTypes' -and
    $whaleInstaller -match 'LSItemContentTypes:0 string public\.html' -and
    $whaleInstaller -match 'NSUserActivityTypeBrowsingWeb' -and
    $whaleLauncher -match 'handleGetURL' -and
    $whaleLauncher -match 'openFiles filenames'
) 'LaunchServices web-handler contract'
Add-Check 'Whale launcher declares macOS media privacy usage' (
    $whaleInstaller -match "key='NSMicrophoneUsageDescription'" -and
    $whaleInstaller -match "key='NSCameraUsageDescription'"
) 'responsible launcher must survive website microphone and camera requests'
Add-Check 'launcher backups cannot shadow the live LaunchServices identity' (
    $whaleInstaller -match '\$lsregister -u \$app' -and
    $whaleInstaller -match '\$backupName = "\$\(Split-Path -Leaf \$app\)\.backup"' -and
    $macInstaller -match '\$lsregister -u \$target' -and
    $macInstaller -match '\$backupName = "\$\(Split-Path -Leaf \$target\)\.backup"'
) 'all macOS launchers unregister before replacement and preserve recovery bundles with a non-.app suffix'
Add-Check 'Whale Dock launcher persistently owns status and focuses the exact CDP slot' (
    $whaleLauncher -match 'applicationShouldHandleReopen' -and
    $whaleLauncher -match 'setActivationPolicy\(\.regular\)' -and
    $whaleLauncher -match 'NSRunningApplication\(processIdentifier:' -and
    $whaleLauncher -match 'startMonitor\(\)' -and
    $whaleLauncher -match 'dockTile\.badgeLabel' -and
    $whaleLauncher -match 'hasExpectedIdentity\(pid:' -and
    $whaleLauncher -match '/json/activate/' -and
    $whaleLauncher -match '/json/new\?' -and
    $whaleLauncher -match 'addingPercentEncoding' -and
    $whaleLauncher -notmatch 'URLQueryItem\(name: "url"' -and
    $whaleLauncher -match 'Target activated' -and
    $whaleLauncher -match 'applicationDidBecomeActive' -and
    $whaleLauncher -match 'hasRestorableSession\(\)' -and
    $whaleLauncher -match '--restore-last-session' -and
    $whaleLauncher -match 'chrome://newtab/' -and
    $whaleLauncher -notmatch 'ps.*-axo'
) 'persistent exact-profile Dock controller'
Add-Check 'Whale launcher creates a visible page after an empty session restore' (
    $whaleLauncher -match 'ensurePageAvailable' -and
    $whaleLauncher -match 'existingPageTargetID' -and
    $whaleLauncher -match 'createPageTarget\("chrome://newtab/"\)' -and
    $whaleLauncher -match '"--max-time", "2", "-fsS"' -and
    $whaleLauncher -match 'could not create a page to show'
) 'zero-page listener recovery'
Add-Check 'Whale Dock Quit stops only the exact CDP engine before launcher exit' (
    $whaleLauncher -match 'applicationShouldTerminate' -and
    $whaleLauncher -match 'return \.terminateLater' -and
    $whaleLauncher -match 'hasExpectedIdentity\(pid: listenerPID\)' -and
    $whaleLauncher -match 'kill\(listenerPID, SIGTERM\)' -and
    $whaleLauncher -match 'waitForBrowserTermination' -and
    $whaleLauncher -match 'reply\(toApplicationShouldTerminate: true\)'
) 'verified child shutdown contract'
Add-Check 'background launch uses AICC environment' (
    $statusLauncher -match 'AICC_BACKGROUND_LAUNCH' -and
    $lease -match 'AICC_BACKGROUND_LAUNCH=1' -and
    $statusLauncher -notmatch 'AGENT_HUB_BACKGROUND_LAUNCH'
) 'background launch contract'
Add-Check 'badge source is canonical and permission minimal' (
    $badgeInstaller -match 'extensions/aicc-cdp-port-badge' -and
    (Test-Path -LiteralPath (Join-Path $extensionRoot 'manifest.json') -PathType Leaf)
) $extensionRoot
Add-Check 'Chrome launcher waits for asynchronous badge application' (
    $statusLauncher -match 'setTimeout\(resolve, 200\)' -and
    $statusLauncher -match 'chrome\.action\.getBadgeText'
) 'prevents repeated hidden popup target churn'
Add-Check 'Whale badge incompatibility is explicit' (
    (Read-Text 'tools/platform/web-automation/install-cdp-port-badge-extension.mjs') -match 'whale_extensions_load_unpacked_unavailable' -and
    $badgeInstaller -match 'badge_status' -and $badgeInstaller -match 'badge_supported'
) 'unsupported is reported, not treated as installed'
if (Test-Path -LiteralPath (Join-Path $extensionRoot 'manifest.json') -PathType Leaf) {
    $manifest = Get-Content -LiteralPath (Join-Path $extensionRoot 'manifest.json') -Raw | ConvertFrom-Json
    $permissions = @($manifest.permissions)
    Add-Check 'badge requests storage only' (
        $manifest.manifest_version -eq 3 -and $manifest.name -eq 'AICC CDP Port Badge' -and
        $permissions.Count -eq 1 -and $permissions[0] -eq 'storage' -and
        $null -eq $manifest.host_permissions -and $null -eq $manifest.content_scripts
    ) 'manifest permissions'
}
Add-Check 'identity guard requires exact endpoint and profile' (
    $identityGuard -match 'ExpectedProfileDir explicitly' -and
    $identityGuard -match 'wrong_browser_profile' -and
    $identityGuard -match 'Only loopback HTTP CDP endpoints are allowed'
) 'listener process profile guard'
Add-Check 'Windows launchers use portable AICC state' (
    $windowsInstaller -match '\.ai-control-center\\browser-launchers' -and
    $windowsInstaller -match 'AI Control Center' -and
    $windowsChrome -match 'AICC_ROOT' -and
    $windowsChrome -match 'aicc-cdp-port-badge' -and
    $windowsWhale -match 'SpecialFolder\.UserProfile' -and
    $windowsWhale -match '"\.ai-control-center", "browser-profiles", "whale", "9335"'
) 'Windows source contract; live Windows verification is separate'

if (Test-Path -LiteralPath $CoordinationPath -PathType Leaf) {
    $stateRoot = [IO.Path]::GetFullPath((Join-Path $HOME '.ai-control-center'))
    $chrome = Read-TomlValue $CoordinationPath browser cdp_profile_dir
    $chrome2 = Read-TomlValue $CoordinationPath browser cdp_slot2_profile_dir
    $whale = Read-TomlValue $CoordinationPath browser cdp_whale_profile_dir
    $qa = Read-TomlValue $CoordinationPath browser cdp_qa_profile_dir
    $bundle = Read-TomlValue $CoordinationPath browser default_browser_bundle_id
    Add-Check 'private coordination points only to AICC browser state' (
        $chrome.StartsWith($stateRoot) -and $chrome2.StartsWith($stateRoot) -and
        $whale.StartsWith($stateRoot) -and $qa.StartsWith($stateRoot)
    ) $CoordinationPath
    Add-Check 'private coordination uses AICC Whale bundle' ($bundle -eq 'com.aicc.whale.cdp.9335') $bundle
} else {
    Add-Check 'private coordination is optional for public checkout' $true 'not installed'
}

$failed = @($checks | Where-Object { -not $_.ok })
$report = [ordered]@{ ok=($failed.Count -eq 0); check_count=$checks.Count; failed_count=$failed.Count; checks=@($checks) }
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 5 } else { $report | ConvertTo-Json -Depth 5 }
if ($failed.Count) { exit 1 }
