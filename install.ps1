$ErrorActionPreference = "Stop"

$ProjectRoot = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $ProjectRoot

if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw "Node.js 20 or newer is required."
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw "npm was not found."
}
if (-not (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
    throw "Python 3.11 or newer is required."
}
if (-not (Get-Command pwsh -ErrorAction SilentlyContinue)) {
    throw "PowerShell 7 (pwsh) is required."
}

if (-not $env:AICC_PYTHON -and (Get-Command python -ErrorAction SilentlyContinue) -and -not (Get-Command py -ErrorAction SilentlyContinue)) {
    $env:AICC_PYTHON = "python"
}

if ((Test-Path .gitmodules) -and (Get-Command git -ErrorAction SilentlyContinue)) {
    git submodule update --init --recursive
}
if ($args -notcontains "--no-link") {
    npm.cmd link
}
node bin/aicc setup
node bin/aicc guidance deploy

Write-Host ""
if ($args -contains "--no-link") {
    Write-Host "Setup complete: node .\bin\aicc open"
} else {
    Write-Host "Setup complete: aicc open"
}
