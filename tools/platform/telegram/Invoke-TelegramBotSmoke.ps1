#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][long]$BotId,
    [string[]]$Command = @('/help','/status','/workspaces','/run missing missing'),
    [string]$Endpoint = '',
    [ValidateRange(10,120)][int]$TimeoutSec = 30
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$CoordinationReader = Join-Path $AiccRoot 'tools\platform\core\Read-AiccCoordination.ps1'
$IdentityGuard = Join-Path $AiccRoot 'tools\platform\web-automation\Assert-CdpEndpointIdentity.ps1'
$Script = Join-Path $PSScriptRoot 'telegram_web_bot_smoke.py'
if (-not $Endpoint) { $Endpoint = [string](& $CoordinationReader -Key browser.cdp_whale_url) }
if (-not $Endpoint) { throw 'cdp_whale_endpoint_missing' }
$ExpectedProfile = [string](& $CoordinationReader -Key browser.cdp_whale_profile_dir)
& $IdentityGuard -ExpectedBrowser whale -Endpoint $Endpoint -ExpectedProfileDir $ExpectedProfile | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Arguments = @($Script,'--endpoint',$Endpoint,'--bot-id',[string]$BotId,'--timeout-sec',[string]$TimeoutSec)
foreach ($Item in $Command) { $Arguments += @('--command',$Item) }
$ChromeBefore = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
$PortBefore = [bool](Get-NetTCPConnection -State Listen -LocalPort 9222 -ErrorAction SilentlyContinue)
$Raw = & python @Arguments
$ExitCode = $LASTEXITCODE
$ChromeAfter = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
$PortAfter = [bool](Get-NetTCPConnection -State Listen -LocalPort 9222 -ErrorAction SilentlyContinue)
$SideEffect = ($ChromeAfter -gt $ChromeBefore) -or (-not $PortBefore -and $PortAfter)
try { $Result = $Raw | ConvertFrom-Json -ErrorAction Stop }
catch { $Result = [pscustomobject]@{ok=$false;error='invalid_smoke_json'}; $ExitCode=2 }
$Result | Add-Member -NotePropertyName chrome_side_effect -NotePropertyValue $SideEffect -Force
$Result | ConvertTo-Json -Depth 7
if ($ExitCode -ne 0 -or $SideEffect -or -not $Result.ok) { exit 2 }
