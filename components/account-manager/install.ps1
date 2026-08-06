# Adds a `cm` shim to a directory on PATH (Windows).
# Creates only the shim; Codex credentials and profiles are left untouched.
$ErrorActionPreference = "Stop"

$repoRoot = $PSScriptRoot
$installDir = if ($env:CM_INSTALL_DIR) { $env:CM_INSTALL_DIR } else { Join-Path $env:LOCALAPPDATA "Programs\cm" }
$launcher = Join-Path $repoRoot "bin\cm.ps1"

if (-not (Test-Path $launcher)) {
    Write-Error "Launcher not found: $launcher"
    exit 1
}

New-Item -ItemType Directory -Force -Path $installDir | Out-Null

# A .cmd shim works from cmd.exe, PowerShell and most terminals, and does not
# require the Developer Mode privileges that symlinks need on Windows.
$shimPath = Join-Path $installDir "cm.cmd"
$shim = @"
@echo off
powershell -NoProfile -ExecutionPolicy Bypass -File "$launcher" %*
exit /b %ERRORLEVEL%
"@
Set-Content -Path $shimPath -Value $shim -Encoding ASCII
Write-Host "Wrote shim: $shimPath"

$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($userPath -notlike "*$installDir*") {
    Write-Host "Note: $installDir is not on your user PATH."
    Write-Host "Add it with: setx PATH `"$env:PATH;$installDir`""
}

Write-Host "Done. Run: cm doctor"
