#requires -Version 7.0
<#
.SYNOPSIS
  Build the registered Windows CDP browser slot launchers and wire their icons.
.DESCRIPTION
  Compiles the tracked launcher sources, copies the tracked slot icons beside
  each executable, and creates Start Menu / Desktop shortcuts whose IconLocation
  points at those icons. A fresh checkout therefore needs no hand-made artwork.

  Browser engines, profiles, sessions, and credentials are never touched. The
  launchers only start or attach to their own registered port and profile.
#>
[CmdletBinding()]
param(
    [string]$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '../../..')).Path,
    [string]$InstallRoot = (Join-Path $HOME '.ai-control-center\browser-launchers'),
    [string[]]$OnlyPorts = @(),
    [switch]$NoShortcuts,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not $IsWindows) {
    throw 'This installer targets Windows. Use Install-SeparatedBrowserAppsOnMac.ps1 on macOS.'
}

$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$launcherSourceRoot = Join-Path $AiccRoot 'tools\platform\web-automation\windows'
$iconRoot = Join-Path $AiccRoot 'tools\platform\app-icons'
$profileRoot = Join-Path $HOME '.ai-control-center\browser-profiles'

$slots = @(
    [ordered]@{
        name = 'CDP Chrome 9222'
        port = '9222'
        source = Join-Path $launcherSourceRoot 'CDPChromeLauncher.cs'
        exe = 'CDP Chrome 9222.exe'
        icon = Join-Path $iconRoot 'cdp_chrome_9222.ico'
        user_data = Join-Path $profileRoot 'chrome\9222\UserData'
        profile_directory = 'Default'
    },
    [ordered]@{
        name = 'CDP Chrome 9223'
        port = '9223'
        source = Join-Path $launcherSourceRoot 'CDPChromeLauncher.cs'
        exe = 'CDP Chrome 9223.exe'
        icon = Join-Path $iconRoot 'cdp_chrome_9223.ico'
        user_data = Join-Path $profileRoot 'chrome\9223\UserData'
        profile_directory = 'Default'
    },
    [ordered]@{
        name = 'CDP Whale 9335'
        port = '9335'
        source = Join-Path $launcherSourceRoot 'CDPWhaleLauncher.cs'
        exe = 'CDP Whale 9335.exe'
        icon = Join-Path $iconRoot 'cdp_whale_cdp.ico'
        user_data = Join-Path $profileRoot 'whale\9335\UserData'
        profile_directory = 'Profile 1'
    }
)
if ($OnlyPorts.Count -gt 0) {
    $slots = @($slots | Where-Object { $_.port -in $OnlyPorts })
    if ($slots.Count -eq 0) { throw "No registered slots matched: $($OnlyPorts -join ', ')" }
}

foreach ($slot in $slots) {
    foreach ($required in @($slot.source, $slot.icon)) {
        if (-not (Test-Path -LiteralPath $required -PathType Leaf)) {
            throw "Required launcher asset is missing from this checkout: $required"
        }
    }
}

$compiler = Get-ChildItem -LiteralPath (Join-Path $env:WINDIR 'Microsoft.NET\Framework64') -Filter 'v4.*' -Directory -ErrorAction SilentlyContinue |
    Sort-Object Name -Descending |
    ForEach-Object { Join-Path $_.FullName 'csc.exe' } |
    Where-Object { Test-Path -LiteralPath $_ -PathType Leaf } |
    Select-Object -First 1
if (-not $compiler) {
    throw 'No .NET Framework C# compiler (csc.exe) was found. Install the .NET Framework developer tooling and retry.'
}

New-Item -ItemType Directory -Force -Path $InstallRoot | Out-Null
$shell = if (-not $NoShortcuts) { New-Object -ComObject WScript.Shell } else { $null }
$startMenu = Join-Path $env:APPDATA 'Microsoft\Windows\Start Menu\Programs\AI Control Center'
if ($shell) { New-Item -ItemType Directory -Force -Path $startMenu | Out-Null }

$results = foreach ($slot in $slots) {
    $exePath = Join-Path $InstallRoot $slot.exe
    $iconTarget = Join-Path $InstallRoot ([IO.Path]::GetFileName($slot.icon))
    Copy-Item -LiteralPath $slot.icon -Destination $iconTarget -Force

    & $compiler /nologo /target:winexe /platform:anycpu ("/out:$exePath") $slot.source | Out-Null
    if ($LASTEXITCODE -ne 0 -or -not (Test-Path -LiteralPath $exePath -PathType Leaf)) {
        throw "Failed to compile the launcher for slot $($slot.port)."
    }

    $shortcutPath = $null
    if ($shell) {
        $shortcutPath = Join-Path $startMenu ("{0}.lnk" -f $slot.name)
        $shortcut = $shell.CreateShortcut($shortcutPath)
        $shortcut.TargetPath = $exePath
        $shortcut.WorkingDirectory = $InstallRoot
        $shortcut.IconLocation = "$iconTarget,0"
        $shortcut.Description = "$($slot.name) - CDP port $($slot.port)"
        $shortcut.Save()
    }

    [ordered]@{
        name = $slot.name
        port = $slot.port
        exe = $exePath
        icon = $iconTarget
        shortcut = $shortcutPath
        user_data = $slot.user_data
        profile_directory = $slot.profile_directory
        installed = (Test-Path -LiteralPath $exePath -PathType Leaf)
    }
}

$report = [ordered]@{
    ok = $true
    aicc_root = $AiccRoot
    install_root = $InstallRoot
    compiler = $compiler
    engine_policy = 'vendor_installed_browsers_unchanged'
    badge_policy = 'install_over_cdp_via_Install-CdpPortBadgeExtension.ps1'
    slots = @($results)
}
if ($AsJson) { $report | ConvertTo-Json -Compress -Depth 6 } else { $report | ConvertTo-Json -Depth 6 }
