[CmdletBinding()]
param(
    [string]$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path,
    [string]$ApplicationsRoot = "$HOME/Applications",
    [switch]$ChatGptOnly,
    [switch]$CdpWhaleOnly,
    [switch]$LaunchAndVerify
)

$ErrorActionPreference = 'Stop'
if (-not $IsMacOS) { throw 'This installer is only for macOS.' }
$launcher = Join-Path $AiccRoot 'tools/platform/web-automation/open_imported_browser_profile_macos.sh'
if (-not (Test-Path -LiteralPath $launcher -PathType Leaf)) { throw "Browser launcher missing: $launcher" }
$portBadgeExtension = Join-Path $AiccRoot 'tools/platform/web-automation/extensions/aicc-cdp-port-badge'
if (-not (Test-Path -LiteralPath (Join-Path $portBadgeExtension 'manifest.json') -PathType Leaf)) {
    throw "CDP port badge extension is missing: $portBadgeExtension"
}
$whaleLauncherSource = Join-Path $AiccRoot 'tools/platform/web-automation/macos/CdpWhaleLauncher.swift'
if (-not (Test-Path -LiteralPath $whaleLauncherSource -PathType Leaf)) {
    throw "CDP Whale native launcher source is missing: $whaleLauncherSource"
}
& /bin/chmod 755 $launcher
New-Item -ItemType Directory -Force -Path $ApplicationsRoot | Out-Null

$definitions = @(
    [ordered]@{name='CDP Chrome 9222';arg='chrome-cdp-primary';bundle='com.aicc.chrome.cdp.9222';port=9222;icon='/Applications/Google Chrome.app/Contents/Resources/app.icns'},
    [ordered]@{name='CDP Chrome 9223';arg='chrome-cdp-bulk';bundle='com.aicc.chrome.cdp.9223';port=9223;icon='/Applications/Google Chrome.app/Contents/Resources/app.icns'},
    [ordered]@{name='CDP Whale';display_name='CDP Whale 9335';arg='whale-cdp';bundle='com.aicc.whale.cdp.9335';port=9335;icon=(Join-Path $AiccRoot 'tools/platform/app-icons/cdp_whale.ico');dedicated_bundle=$true},
    [ordered]@{name='Chrome - Windows Profile';arg='chrome-main';bundle='com.aicc.imported.chrome.windows-profile';port=$null;icon='/Applications/Google Chrome.app/Contents/Resources/app.icns'}
)
if ($ChatGptOnly) {
    $definitions = @($definitions | Where-Object { $_.bundle -like 'com.aicc.chrome.cdp.*' })
}
if ($CdpWhaleOnly) {
    $definitions = @($definitions | Where-Object { $_.bundle -eq 'com.aicc.whale.cdp.9335' })
}
$records = @()
$resolvedApplicationsRoot = [IO.Path]::GetFullPath($ApplicationsRoot)
$logRoot = Join-Path $HOME '.ai-control-center/logs/browser'
$lsregister = '/System/Library/Frameworks/CoreServices.framework/Frameworks/LaunchServices.framework/Support/lsregister'
New-Item -ItemType Directory -Force -Path $logRoot | Out-Null
foreach ($definition in $definitions) {
    $app = [IO.Path]::GetFullPath((Join-Path $resolvedApplicationsRoot ($definition.name + '.app')))
    if (-not $app.StartsWith($resolvedApplicationsRoot + [IO.Path]::DirectorySeparatorChar, [StringComparison]::Ordinal)) {
        throw "Application path escaped ApplicationsRoot: $app"
    }
    if (Test-Path -LiteralPath $app) {
        $running = @(& /usr/bin/pgrep -lf ([regex]::Escape("$app/Contents/MacOS/")) 2>$null)
        if ($running.Count -gt 0) { throw "Target browser is running: $app" }
        $backupRoot = Join-Path $HOME (".ai-control-center/backups/browser-launchers/{0}_imported-browser-app-replace" -f (Get-Date -Format 'yyyyMMdd_HHmmss'))
        New-Item -ItemType Directory -Force -Path $backupRoot | Out-Null
        if (Test-Path -LiteralPath $lsregister -PathType Leaf) {
            & $lsregister -u $app | Out-Null
        }
        # A backup that still ends in .app remains discoverable by LaunchServices.
        # That leaves multiple launch candidates for one bundle ID and can route a
        # Dock or URL open request to an obsolete launcher. Keep the bundle intact
        # for recovery, but use a non-application suffix until it is restored.
        $backupName = "$(Split-Path -Leaf $app).backup"
        Move-Item -LiteralPath $app -Destination (Join-Path $backupRoot $backupName)
    }
    $log = Join-Path $logRoot (($definition.bundle -replace '[^A-Za-z0-9._-]','_') + '.log')
    if ($definition.dedicated_bundle) {
        $sourceApp = '/Applications/Whale.app'
        $sourceExecutable = Join-Path $sourceApp 'Contents/MacOS/Whale'
        if (-not (Test-Path -LiteralPath $sourceApp -PathType Container)) {
            throw "Whale application missing: $sourceApp"
        }
        if (-not (Test-Path -LiteralPath $sourceExecutable -PathType Leaf)) {
            throw "Whale executable missing: $sourceExecutable"
        }
        New-Item -ItemType Directory -Force -Path (Join-Path $app 'Contents/MacOS') | Out-Null
        New-Item -ItemType Directory -Force -Path (Join-Path $app 'Contents/Resources') | Out-Null
        $macos = Join-Path $app 'Contents/MacOS'
        $wrapperPath = Join-Path $macos 'CDP Whale Launcher'
        & /usr/bin/xcrun swiftc -O -framework AppKit -framework Carbon $whaleLauncherSource -o $wrapperPath
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $wrapperPath -PathType Leaf)) {
            throw "Failed to compile native CDP Whale launcher: $wrapperPath"
        }
        $plist = Join-Path $app 'Contents/Info.plist'
        & /usr/bin/plutil -create xml1 $plist
        if ($LASTEXITCODE -ne 0) { throw "Failed to create lightweight Whale launcher plist: $plist" }
    } else {
        $shellCommand = "nohup '$launcher' '$($definition.arg)' >'$log' 2>&1 &"
        $appleScript = 'do shell script "' + ($shellCommand.Replace('\','\\').Replace('"','\"')) + '"'
        & /usr/bin/osacompile -o $app -e $appleScript
        if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $app -PathType Container)) {
            throw "Failed to compile app bundle: $($definition.name)"
        }
    }
    $contents = Join-Path $app 'Contents'
    $resources = Join-Path $contents 'Resources'
    if ($definition.dedicated_bundle -and (Test-Path -LiteralPath $definition.icon -PathType Leaf)) {
        $iconset = Join-Path ([IO.Path]::GetTempPath()) ("cdp-whale-{0}.iconset" -f [Guid]::NewGuid().ToString('N'))
        $iconSource = Join-Path ([IO.Path]::GetTempPath()) ("cdp-whale-{0}.png" -f [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $iconset | Out-Null
        & /usr/bin/sips -s format png $definition.icon --out $iconSource *> $null
        if ($LASTEXITCODE -ne 0) { throw 'Failed to convert the CDP Whale source icon to PNG.' }
        foreach ($icon in @(
            @{px=16;name='icon_16x16.png'}, @{px=32;name='icon_16x16@2x.png'},
            @{px=32;name='icon_32x32.png'}, @{px=64;name='icon_32x32@2x.png'},
            @{px=128;name='icon_128x128.png'}, @{px=256;name='icon_128x128@2x.png'},
            @{px=256;name='icon_256x256.png'}, @{px=512;name='icon_256x256@2x.png'},
            @{px=512;name='icon_512x512.png'}, @{px=1024;name='icon_512x512@2x.png'}
        )) {
            & /usr/bin/sips -z $icon.px $icon.px $iconSource --out (Join-Path $iconset $icon.name) *> $null
            if ($LASTEXITCODE -ne 0) { throw "Failed to render CDP Whale icon size $($icon.px)." }
        }
        & /usr/bin/iconutil -c icns $iconset -o (Join-Path $resources 'app.icns')
        if ($LASTEXITCODE -ne 0) { throw 'Failed to compile CDP Whale icon.' }
        Remove-Item -LiteralPath $iconset -Recurse -Force
        Remove-Item -LiteralPath $iconSource -Force
    } elseif (Test-Path -LiteralPath $definition.icon -PathType Leaf) {
        Copy-Item -LiteralPath $definition.icon -Destination (Join-Path $resources 'applet.icns') -Force
    }
    $plist = Join-Path $contents 'Info.plist'
    $displayName = if ($definition.display_name) { [string]$definition.display_name } else { [string]$definition.name }
    $plistEntries = @(
        [ordered]@{key='CFBundleDisplayName';value=$displayName},
        [ordered]@{key='CFBundleIdentifier';value=$definition.bundle},
        [ordered]@{key='CFBundleName';value=$displayName}
    )
    if ($definition.dedicated_bundle) {
        $plistEntries += @(
            [ordered]@{key='CFBundleExecutable';value='CDP Whale Launcher'},
            [ordered]@{key='CFBundlePackageType';value='APPL'},
            [ordered]@{key='CFBundleIconFile';value='app.icns'},
            [ordered]@{key='CFBundleShortVersionString';value='2.0'},
            [ordered]@{key='CFBundleVersion';value='2'},
            [ordered]@{key='NSMicrophoneUsageDescription';value='CDP Whale requests microphone access only when a website you allow uses audio input.'},
            [ordered]@{key='NSCameraUsageDescription';value='CDP Whale requests camera access only when a website you allow uses video input.'}
        )
    } else {
        $plistEntries += @(
            [ordered]@{key='CFBundleShortVersionString';value='1.0'},
            [ordered]@{key='CFBundleVersion';value='1'}
        )
    }
    foreach ($entry in $plistEntries) {
        & /usr/libexec/PlistBuddy -c "Set :$($entry.key) $($entry.value)" $plist 2>$null
        if ($LASTEXITCODE -ne 0) {
            & /usr/libexec/PlistBuddy -c "Add :$($entry.key) string $($entry.value)" $plist
            if ($LASTEXITCODE -ne 0) { throw "Failed to set plist key $($entry.key) for $($definition.name)" }
        }
    }
    if ($definition.dedicated_bundle) {
        & /usr/libexec/PlistBuddy -c 'Delete :LSUIElement' $plist 2>$null
        # Keep a distinct persistent Dock status/focus tile while the exact
        # vendor Whale process owns the browser windows and authenticated
        # profile. This preserves vendor signing and Keychain access.
        # Register the lightweight launcher as the web handler. LaunchServices
        # then forwards URLs and HTML files to this wrapper, which passes them
        # to the unchanged vendor Whale process with the verified AICC profile.
        foreach ($key in @('CFBundleURLTypes', 'CFBundleDocumentTypes', 'NSUserActivityTypes')) {
            & /usr/libexec/PlistBuddy -c "Delete :$key" $plist 2>$null
        }
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes array' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0 dict' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLName string Web site URL' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleTypeRole string Viewer' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes array' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes:0 string http' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleURLTypes:0:CFBundleURLSchemes:1 string https' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes array' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes:0 dict' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes:0:CFBundleTypeName string HTML document' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes:0:CFBundleTypeRole string Viewer' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes:0:LSItemContentTypes array' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes:0:LSItemContentTypes:0 string public.html' $plist
        & /usr/libexec/PlistBuddy -c 'Add :CFBundleDocumentTypes:0:LSItemContentTypes:1 string public.xhtml' $plist
        & /usr/libexec/PlistBuddy -c 'Add :NSUserActivityTypes array' $plist
        & /usr/libexec/PlistBuddy -c 'Add :NSUserActivityTypes:0 string NSUserActivityTypeBrowsingWeb' $plist
        if ($LASTEXITCODE -ne 0) { throw 'Failed to register CDP Whale web handlers.' }
    }
    & /usr/bin/plutil -lint $plist | Out-Null
    & /usr/bin/codesign --force --sign - $app 2>$null
    if ($LASTEXITCODE -ne 0) { throw "Failed to sign app bundle: $($definition.name)" }
    & /usr/bin/touch $app
    $installedVersion = [string](& /usr/libexec/PlistBuddy -c 'Print :CFBundleShortVersionString' $plist 2>$null)
    $records += [ordered]@{
        name = $definition.name
        display_name = $displayName
        app = $app
        profile = $definition.arg
        port = $definition.port
        version = $installedVersion
        installed = $true
        kind = $(if ($definition.dedicated_bundle) {'persistent-status-web-handler-vendor-browser-launcher'} else {'launcher'})
    }
}

if (Test-Path -LiteralPath $lsregister) {
    foreach ($record in $records) { & $lsregister -f $record.app | Out-Null }
}

if ($LaunchAndVerify) {
    foreach ($record in $records) {
        & /usr/bin/open -n $record.app
        if ($record.port) {
            $ready = $false
            foreach ($attempt in 1..120) {
                Start-Sleep -Milliseconds 500
                & /usr/bin/curl -fsS "http://127.0.0.1:$($record.port)/json/version" *> $null
                if ($LASTEXITCODE -eq 0) { $ready = $true; break }
            }
            if (-not $ready -and $record.name -eq 'CDP Whale') {
                $normalWhale = @(& /usr/bin/pgrep -lf '/Applications/Whale.app/Contents/MacOS/Whale' 2>$null)
                if ($normalWhale.Count -gt 0) {
                    $record['verification'] = 'deferred-existing-normal-whale-must-be-closed-before-cdp-whale'
                    continue
                }
            }
            if (-not $ready) { throw "$($record.name) did not expose CDP port $($record.port)." }
            $record['verification'] = 'cdp-ready'
        } else {
            $record['verification'] = 'launch-request-accepted'
        }
    }
}

[ordered]@{status='installed';applications_root=$ApplicationsRoot;apps=$records;launch_verified=[bool]$LaunchAndVerify} | ConvertTo-Json -Depth 5
