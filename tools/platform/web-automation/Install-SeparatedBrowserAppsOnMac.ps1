[CmdletBinding()]
param(
    [string]$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path,
    [string]$ApplicationsRoot = "$HOME/Applications",
    [string]$ChromeApp = "/Applications/Google Chrome.app",
    [string]$PrimaryUserData = "$HOME/.ai-control-center/browser-profiles/chrome/9222/UserData",
    [string]$SecondaryUserData = "$HOME/.ai-control-center/browser-profiles/chrome/9223/UserData",
    [string]$NormalUserData = "$HOME/Library/Application Support/Google/Chrome",
    [string[]]$OnlyPorts = @(),
    [switch]$NormalOnly,
    [switch]$Replace,
    [switch]$RegisterDock
)

$ErrorActionPreference = 'Stop'
if (-not $IsMacOS) { throw 'This installer is only for macOS.' }

$lsregister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'

$resolvedApplicationsRoot = [IO.Path]::GetFullPath($ApplicationsRoot)
New-Item -ItemType Directory -Force -Path $resolvedApplicationsRoot | Out-Null

$sourceApp = [IO.Path]::GetFullPath($ChromeApp)
$sourceExecutable = Join-Path $sourceApp 'Contents/MacOS/Google Chrome'
if (-not (Test-Path -LiteralPath $sourceApp -PathType Container) -or
    -not (Test-Path -LiteralPath $sourceExecutable -PathType Leaf)) {
    throw "Official Google Chrome application is missing or invalid: $sourceApp"
}
$sourceBundle = [string](& /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' (Join-Path $sourceApp 'Contents/Info.plist') 2>$null)
if ($sourceBundle -ne 'com.google.Chrome') {
    throw "CDP Chrome source must be official Google Chrome (com.google.Chrome), actual: $sourceBundle"
}
$sourceSignature = (& /usr/bin/codesign -dv --verbose=4 $sourceExecutable 2>&1 | Out-String)
if ($LASTEXITCODE -ne 0 -or $sourceSignature -notmatch '(?m)^TeamIdentifier=(.+)$') {
    throw "Official Google Chrome executable has no verifiable signing team: $sourceExecutable"
}
$sourceTeamIdentifier = $Matches[1].Trim()
$statusLauncherSource = Join-Path $AiccRoot 'tools/platform/web-automation/macos/CdpChromeStatusLauncher.swift'
if (-not (Test-Path -LiteralPath $statusLauncherSource -PathType Leaf)) {
    throw "Persistent CDP Chrome status launcher source is missing: $statusLauncherSource"
}
$normalLauncherSource = Join-Path $AiccRoot 'tools/platform/web-automation/macos/NormalChromeLauncher.swift'
if (-not (Test-Path -LiteralPath $normalLauncherSource -PathType Leaf)) {
    throw "Normal Chrome launcher source is missing: $normalLauncherSource"
}
$portBadgeExtension = Join-Path $AiccRoot 'tools/platform/web-automation/extensions/aicc-cdp-port-badge'
if (-not (Test-Path -LiteralPath (Join-Path $portBadgeExtension 'manifest.json') -PathType Leaf)) {
    throw "CDP port badge extension is missing: $portBadgeExtension"
}

$variants = @(
    [ordered]@{
        name = 'CDP Chrome 9222'
        bundle = 'com.aicc.chrome.cdp.9222'
        user_data = $PrimaryUserData
        user_data_env = 'CDP_CHROME_9222_USER_DATA_DIR'
        profile_env = 'CDP_CHROME_9222_PROFILE_DIRECTORY'
        port = '9222'
        port_env = 'CDP_CHROME_9222_PORT'
        icon = Join-Path $AiccRoot 'tools/platform/app-icons/cdp_chrome_9222.png'
        url = 'https://chatgpt.com/'
        require_profile = $false
    },
    [ordered]@{
        name = 'CDP Chrome 9223'
        bundle = 'com.aicc.chrome.cdp.9223'
        user_data = $SecondaryUserData
        user_data_env = 'CDP_CHROME_9223_USER_DATA_DIR'
        profile_env = 'CDP_CHROME_9223_PROFILE_DIRECTORY'
        port = '9223'
        port_env = 'CDP_CHROME_9223_PORT'
        icon = Join-Path $AiccRoot 'tools/platform/app-icons/cdp_chrome_9223.png'
        url = 'https://chatgpt.com/'
        require_profile = $false
    }
)
if ($NormalOnly) {
    $variants = @()
} elseif ($OnlyPorts.Count -gt 0) {
    $variants = @($variants | Where-Object { [string]$_['port'] -in $OnlyPorts })
    if ($variants.Count -eq 0) { throw "No requested CDP Chrome ports matched: $($OnlyPorts -join ', ')" }
}

function New-NormalChromeApp {
    $target = [IO.Path]::GetFullPath((Join-Path $resolvedApplicationsRoot 'Google Chrome (일반).app'))
    $normalRoot = [IO.Path]::GetFullPath($NormalUserData)
    if (-not $normalRoot.StartsWith($HOME + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)) {
        throw "Normal Chrome user-data directory must remain under the user home: $normalRoot"
    }
    if ($normalRoot -in @($PrimaryUserData, $SecondaryUserData)) {
        throw 'Normal Chrome must not share a user-data directory with a CDP slot.'
    }
    New-Item -ItemType Directory -Force -Path $normalRoot | Out-Null

    if (Test-Path -LiteralPath $target) {
        $running = @(& /usr/bin/pgrep -lf ([regex]::Escape("$target/Contents/MacOS/Normal Chrome Launcher")) 2>$null)
        if ($running.Count -gt 0) { throw "Target browser is running: $target" }
        if (-not $Replace) { throw "Target application already exists; use -Replace after backup: $target" }
        $backupRoot = Join-Path $HOME (".ai-control-center/backups/browser-launchers/{0}_normal-chrome-app-replace" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        if (Test-Path -LiteralPath $lsregister -PathType Leaf) { & $lsregister -u $target | Out-Null }
        $backupName = "$(Split-Path -Leaf $target).backup"
        Move-Item -LiteralPath $target -Destination (Join-Path $backupRoot $backupName)
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $target 'Contents/MacOS') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $target 'Contents/Resources') | Out-Null
    $wrapperName = 'Normal Chrome Launcher'
    $wrapperPath = Join-Path $target "Contents/MacOS/$wrapperName"
    & /usr/bin/xcrun swiftc -O -framework AppKit $normalLauncherSource -o $wrapperPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $wrapperPath -PathType Leaf)) {
        throw "Failed to compile normal Chrome launcher: $wrapperPath"
    }

    $plist = Join-Path $target 'Contents/Info.plist'
    & /usr/bin/plutil -create xml1 $plist
    Set-PlistString -Path $plist -Key 'CFBundleIdentifier' -Value 'com.aicc.chrome.normal'
    Set-PlistString -Path $plist -Key 'CFBundleDisplayName' -Value 'Google Chrome (일반)'
    Set-PlistString -Path $plist -Key 'CFBundleName' -Value 'Google Chrome (일반)'
    Set-PlistString -Path $plist -Key 'CFBundleExecutable' -Value $wrapperName
    Set-PlistString -Path $plist -Key 'CFBundlePackageType' -Value 'APPL'
    Set-PlistString -Path $plist -Key 'CFBundleShortVersionString' -Value '1.0'
    Set-PlistString -Path $plist -Key 'CFBundleVersion' -Value '1'
    Set-PlistString -Path $plist -Key 'CFBundleIconFile' -Value 'app.icns'
    Set-PlistBoolean -Path $plist -Key 'LSMultipleInstancesProhibited' -Value $true
    Set-PlistString -Path $plist -Key 'AICCLauncherMode' -Value 'normal_profile_status_controller'
    Set-PlistString -Path $plist -Key 'AICCChromeApplication' -Value $sourceApp
    Set-PlistString -Path $plist -Key 'AICCChromeExecutable' -Value $sourceExecutable
    Set-PlistString -Path $plist -Key 'AICCUserData' -Value $normalRoot
    Set-PlistString -Path $plist -Key 'AICCProfileDirectory' -Value 'Default'
    Set-PlistString -Path $plist -Key 'AICCStartURL' -Value 'chrome://newtab/'

    $vendorIcon = Join-Path $sourceApp 'Contents/Resources/app.icns'
    if (-not (Test-Path -LiteralPath $vendorIcon -PathType Leaf)) { throw "Google Chrome icon is missing: $vendorIcon" }
    Copy-Item -LiteralPath $vendorIcon -Destination (Join-Path $target 'Contents/Resources/app.icns')
    & /usr/bin/plutil -lint $plist | Out-Null
    & /usr/bin/codesign --force --sign - $target 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Failed to sign normal Chrome launcher: $target" }
    & /usr/bin/codesign --verify --deep --strict $target 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Normal Chrome launcher failed strict signature verification: $target" }
    & /usr/bin/touch $target

    return [ordered]@{
        name = 'Google Chrome (일반)'
        app = $target
        bundle = 'com.aicc.chrome.normal'
        user_data = $normalRoot
        profile = 'Default'
        port = $null
        engine = $sourceExecutable
        source_engine_team = $sourceTeamIdentifier
        engine_signature = 'vendor_signed_google_chrome_unchanged'
        runtime_model = 'normal_profile_status_controller_via_launchservices'
        installed = $true
    }
}

function Set-PlistString {
    param([string]$Path, [string]$Key, [string]$Value)
    & /usr/libexec/PlistBuddy -c "Set :$Key $Value" $Path 2>$null
    if ($LASTEXITCODE -ne 0) {
        & /usr/libexec/PlistBuddy -c "Add :$Key string $Value" $Path
        if ($LASTEXITCODE -ne 0) { throw "Failed to set plist key $Key in $Path" }
    }
}

function Set-PlistBoolean {
    param([string]$Path, [string]$Key, [bool]$Value)
    $literal = if ($Value) { 'true' } else { 'false' }
    & /usr/libexec/PlistBuddy -c "Set :$Key $literal" $Path 2>$null
    if ($LASTEXITCODE -ne 0) {
        & /usr/libexec/PlistBuddy -c "Add :$Key bool $literal" $Path
        if ($LASTEXITCODE -ne 0) { throw "Failed to set plist key $Key in $Path" }
    }
}

function New-IcnsFromPng {
    param([string]$Source, [string]$Destination)
    if (-not (Test-Path -LiteralPath $Source -PathType Leaf)) { throw "Icon source missing: $Source" }
    $iconset = Join-Path ([IO.Path]::GetTempPath()) ("separated-browser-{0}.iconset" -f [Guid]::NewGuid().ToString('N'))
    New-Item -ItemType Directory -Path $iconset | Out-Null
    try {
        foreach ($icon in @(
            @{px=16;name='icon_16x16.png'}, @{px=32;name='icon_16x16@2x.png'},
            @{px=32;name='icon_32x32.png'}, @{px=64;name='icon_32x32@2x.png'},
            @{px=128;name='icon_128x128.png'}, @{px=256;name='icon_128x128@2x.png'},
            @{px=256;name='icon_256x256.png'}, @{px=512;name='icon_256x256@2x.png'},
            @{px=512;name='icon_512x512.png'}, @{px=1024;name='icon_512x512@2x.png'}
        )) {
            & /usr/bin/sips -z $icon.px $icon.px $Source --out (Join-Path $iconset $icon.name) *> $null
            if ($LASTEXITCODE -ne 0) { throw "Failed to render icon size $($icon.px)." }
        }
        & /usr/bin/iconutil -c icns $iconset -o $Destination
        if ($LASTEXITCODE -ne 0) { throw "Failed to compile icon: $Destination" }
    } finally {
        if (Test-Path -LiteralPath $iconset) { Remove-Item -LiteralPath $iconset -Recurse -Force }
    }
}

function New-SeparatedChromeApp {
    param([System.Collections.IDictionary]$Definition)

    $target = [IO.Path]::GetFullPath((Join-Path $resolvedApplicationsRoot ($Definition.name + '.app')))
    if (-not $target.StartsWith($resolvedApplicationsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)) {
        throw "Application path escaped ApplicationsRoot: $target"
    }

    if ($Definition.user_data -match '[/\\](ImportedWindowsProfiles|imported-windows)[/\\]') {
        throw "Imported Windows browser profiles are preservation-only and cannot be used as live macOS CDP profiles: $($Definition.user_data)"
    }
    if ($Definition.require_profile -and -not (Test-Path -LiteralPath (Join-Path $Definition.user_data 'Default') -PathType Container)) {
        throw "Required browser profile missing: $($Definition.user_data)/Default"
    }
    New-Item -ItemType Directory -Force -Path $Definition.user_data | Out-Null

    if (Test-Path -LiteralPath $target) {
        $running = @(& /usr/bin/pgrep -lf ([regex]::Escape("$target/Contents/MacOS/CDP Chrome Launcher")) 2>$null)
        if ($running.Count -gt 0) { throw "Target browser is running: $target" }
        if (-not $Replace) { throw "Target application already exists; use -Replace after backup: $target" }
        $backupRoot = Join-Path $HOME (".ai-control-center/backups/browser-launchers/{0}_separated-browser-app-replace" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        if (Test-Path -LiteralPath $lsregister -PathType Leaf) { & $lsregister -u $target | Out-Null }
        $backupName = "$(Split-Path -Leaf $target).backup"
        Move-Item -LiteralPath $target -Destination (Join-Path $backupRoot $backupName)
    }

    New-Item -ItemType Directory -Force -Path (Join-Path $target 'Contents/MacOS') | Out-Null
    New-Item -ItemType Directory -Force -Path (Join-Path $target 'Contents/Resources') | Out-Null
    $macos = Join-Path $target 'Contents/MacOS'
    $wrapperName = 'CDP Chrome Launcher'
    $wrapperPath = Join-Path $macos $wrapperName
    if (-not $Definition.user_data.StartsWith($HOME + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)) {
        throw "Browser user-data directory must remain under the user home: $($Definition.user_data)"
    }
    & /usr/bin/xcrun swiftc -O -framework AppKit $statusLauncherSource -o $wrapperPath
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $wrapperPath -PathType Leaf)) {
        throw "Failed to compile persistent CDP Chrome status launcher: $wrapperPath"
    }

    $plist = Join-Path $target 'Contents/Info.plist'
    & /usr/bin/plutil -create xml1 $plist
    if ($LASTEXITCODE -ne 0) { throw "Failed to create app plist: $plist" }
    Set-PlistString -Path $plist -Key 'CFBundleIdentifier' -Value $Definition.bundle
    Set-PlistString -Path $plist -Key 'CFBundleDisplayName' -Value $Definition.name
    Set-PlistString -Path $plist -Key 'CFBundleName' -Value $Definition.name
    Set-PlistString -Path $plist -Key 'CFBundleExecutable' -Value $wrapperName
    Set-PlistString -Path $plist -Key 'CFBundlePackageType' -Value 'APPL'
    Set-PlistString -Path $plist -Key 'CFBundleShortVersionString' -Value '2.0'
    Set-PlistString -Path $plist -Key 'CFBundleVersion' -Value '2'
    Set-PlistString -Path $plist -Key 'CFBundleIconFile' -Value 'app.icns'
    Set-PlistBoolean -Path $plist -Key 'LSMultipleInstancesProhibited' -Value $true
    Set-PlistString -Path $plist -Key 'AICCLauncherMode' -Value 'persistent_slot_status_controller'
    Set-PlistString -Path $plist -Key 'AICCChromeApplication' -Value $sourceApp
    Set-PlistString -Path $plist -Key 'AICCChromeExecutable' -Value $sourceExecutable
    Set-PlistString -Path $plist -Key 'AICCUserData' -Value $Definition.user_data
    Set-PlistString -Path $plist -Key 'AICCUserDataEnvironment' -Value $Definition.user_data_env
    Set-PlistString -Path $plist -Key 'AICCProfileDirectory' -Value 'Default'
    Set-PlistString -Path $plist -Key 'AICCProfileEnvironment' -Value $Definition.profile_env
    Set-PlistString -Path $plist -Key 'AICCPort' -Value $Definition.port
    Set-PlistString -Path $plist -Key 'AICCPortEnvironment' -Value $Definition.port_env
    Set-PlistString -Path $plist -Key 'AICCStartURL' -Value $Definition.url
    Set-PlistString -Path $plist -Key 'AICCBadgeExtension' -Value $portBadgeExtension

    $resources = Join-Path $target 'Contents/Resources'
    New-IcnsFromPng -Source $Definition.icon -Destination (Join-Path $resources 'app.icns')

    & /usr/bin/plutil -lint $plist | Out-Null
    & /usr/bin/codesign --force --sign - $target 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Failed to sign lightweight launcher app: $target" }
    & /usr/bin/codesign --verify --deep --strict $target 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Installed app bundle failed strict signature verification: $target" }
    & /usr/bin/touch $target

    return [ordered]@{
        name = $Definition.name
        app = $target
        bundle = $Definition.bundle
        user_data = $Definition.user_data
        profile = 'Default'
        port = $Definition.port
        engine = $sourceExecutable
        source_engine_team = $sourceTeamIdentifier
        engine_signature = 'vendor_signed_google_chrome_unchanged'
        runtime_model = 'persistent_slot_status_controller_via_launchservices'
        installed = $true
    }
}

function Register-SeparatedBrowserDock {
    $dockItems = @(
        [ordered]@{name='Google Chrome (일반)';bundle='com.aicc.chrome.normal';path=(Join-Path $resolvedApplicationsRoot 'Google Chrome (일반).app')},
        [ordered]@{name='CDP Chrome 9222';bundle='com.aicc.chrome.cdp.9222';path=(Join-Path $resolvedApplicationsRoot 'CDP Chrome 9222.app')},
        [ordered]@{name='CDP Chrome 9223';bundle='com.aicc.chrome.cdp.9223';path=(Join-Path $resolvedApplicationsRoot 'CDP Chrome 9223.app')},
        [ordered]@{name='NAVER Whale';bundle='com.naver.Whale';path='/Applications/Whale.app'},
        [ordered]@{name='CDP Whale 9335';bundle='com.aicc.whale.cdp.9335';path=(Join-Path $resolvedApplicationsRoot 'CDP Whale.app')}
    )

    foreach ($item in $dockItems) {
        if (-not (Test-Path -LiteralPath $item.path -PathType Container)) { throw "Dock application missing: $($item.path)" }
        $actualBundle = [string](& /usr/libexec/PlistBuddy -c 'Print :CFBundleIdentifier' (Join-Path $item.path 'Contents/Info.plist') 2>$null)
        if ($actualBundle -ne $item.bundle) {
            throw "Dock bundle mismatch for $($item.name): expected=$($item.bundle); actual=$actualBundle"
        }
    }

    $dockBackupRoot = Join-Path $HOME (".ai-control-center/backups/browser-launchers/{0}_separated-browser-dock" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
    New-Item -ItemType Directory -Force -Path $dockBackupRoot | Out-Null
    & /usr/bin/defaults export com.apple.dock (Join-Path $dockBackupRoot 'com.apple.dock.before.plist')
    if ($LASTEXITCODE -ne 0) { throw 'Failed to back up Dock preferences.' }

    $dockTemp = Join-Path ([IO.Path]::GetTempPath()) ("separated-browser-dock-{0}.plist" -f [Guid]::NewGuid().ToString('N'))
    & /usr/bin/defaults export com.apple.dock $dockTemp
    if ($LASTEXITCODE -ne 0) { throw 'Failed to export Dock preferences.' }
    try {
        $browserBundles = @(
            'com.google.Chrome', 'com.google.chrome.for.testing', 'com.aicc.chrome.normal',
            'com.aicc.chrome.cdp.9222', 'com.aicc.chrome.cdp.9223',
            'com.naver.Whale', 'com.aicc.whale.cdp.9335'
        )
        $removeIndices = @()
        for ($index = 0; $index -lt 100; $index++) {
            $bundle = [string](& /usr/libexec/PlistBuddy -c "Print :persistent-apps:${index}:tile-data:bundle-identifier" $dockTemp 2>$null)
            if ($LASTEXITCODE -ne 0) { break }
            if ($bundle -in $browserBundles) { $removeIndices += $index }
        }
        $insertAt = if ($removeIndices.Count -gt 0) { [int](($removeIndices | Measure-Object -Minimum).Minimum) } else { 3 }
        foreach ($index in @($removeIndices | Sort-Object -Descending)) {
            & /usr/libexec/PlistBuddy -c "Delete :persistent-apps:$index" $dockTemp
            if ($LASTEXITCODE -ne 0) { throw "Failed to remove stale Dock browser entry at index $index." }
        }

        for ($dockIndex = $dockItems.Count - 1; $dockIndex -ge 0; $dockIndex--) {
            $item = $dockItems[$dockIndex]
            $encodedPath = ($item.path -replace ' ', '%20').TrimEnd('/')
            $url = "file://$encodedPath/"
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt} dict" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-type string file-tile" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data dict" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:bundle-identifier string $($item.bundle)" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:dock-extra bool false" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:file-data dict" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:file-data:_CFURLString string $url" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:file-data:_CFURLStringType integer 15" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:file-label string $($item.name)" $dockTemp
            & /usr/libexec/PlistBuddy -c "Add :persistent-apps:${insertAt}:tile-data:file-type integer 41" $dockTemp
            if ($LASTEXITCODE -ne 0) { throw "Failed to add Dock entry: $($item.name)" }
        }

        & /usr/bin/plutil -lint $dockTemp | Out-Null
        & /usr/bin/defaults import com.apple.dock $dockTemp
        if ($LASTEXITCODE -ne 0) { throw 'Failed to import Dock preferences.' }
        & /usr/bin/killall Dock 2>$null
    } finally {
        if (Test-Path -LiteralPath $dockTemp) { Remove-Item -LiteralPath $dockTemp -Force }
    }

    return [ordered]@{
        registered = $true
        order = @($dockItems | ForEach-Object { $_.name })
        backup = $dockBackupRoot
    }
}

$normalRecord = New-NormalChromeApp
$records = @()
foreach ($variant in $variants) {
    $records += New-SeparatedChromeApp -Definition $variant
}

if (Test-Path -LiteralPath $lsregister) {
    & $lsregister -f $normalRecord.app | Out-Null
    foreach ($record in $records) { & $lsregister -f $record.app | Out-Null }
}

$dock = if ($RegisterDock) { Register-SeparatedBrowserDock } else { $null }
[ordered]@{
    status = 'installed'
    source_app = $sourceApp
    applications_root = $resolvedApplicationsRoot
    apps = @($normalRecord) + @($records)
    dock = $dock
} | ConvertTo-Json -Depth 6
