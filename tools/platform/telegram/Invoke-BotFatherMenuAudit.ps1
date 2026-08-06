#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidatePattern('^@[A-Za-z0-9_]{5,32}$')]
    [string]$BotUsername,

    [string]$Endpoint = '',
    [ValidateRange(10, 300)]
    [int]$TimeoutSec = 60
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$CoordinationReader = Join-Path $AiccRoot 'tools\platform\core\Read-AiccCoordination.ps1'
$IdentityGuard = Join-Path $AiccRoot 'tools\platform\web-automation\Assert-CdpEndpointIdentity.ps1'
$AuditScript = Join-Path $PSScriptRoot 'botfather_menu_audit.py'

if (-not $Endpoint) {
    $Endpoint = [string](& $CoordinationReader -Key browser.cdp_whale_url)
}
if (-not $Endpoint) {
    throw 'cdp_whale_endpoint_missing'
}

$ExpectedProfile = [string](& $CoordinationReader -Key browser.cdp_whale_profile_dir)
& $IdentityGuard -ExpectedBrowser whale -Endpoint $Endpoint -ExpectedProfileDir $ExpectedProfile | Out-Null
if ($LASTEXITCODE -ne 0) {
    exit $LASTEXITCODE
}

$ChromeBefore = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
$Chrome9222Before = [bool](Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue)

$Raw = & python $AuditScript --endpoint $Endpoint --bot-username $BotUsername --timeout-sec $TimeoutSec
$PythonExit = $LASTEXITCODE
$ChromeAfter = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
$Chrome9222After = [bool](Get-NetTCPConnection -LocalPort 9222 -State Listen -ErrorAction SilentlyContinue)

try {
    $Result = $Raw | ConvertFrom-Json -ErrorAction Stop
} catch {
    $Result = [pscustomobject]@{ ok = $false; error = 'invalid_audit_json' }
    $PythonExit = 2
}

$ChromeSideEffect = ($ChromeAfter -gt $ChromeBefore) -or (-not $Chrome9222Before -and $Chrome9222After)
$Output = [ordered]@{
    ok = ([bool]$Result.ok -and $PythonExit -eq 0 -and -not $ChromeSideEffect)
    bot_username = [string]$Result.bot_username
    endpoint = $Endpoint
    verified_botfather = [bool]$Result.verified_botfather
    edit_menu_buttons = @($Result.edit_menu_buttons)
    username_edit_available = [bool]$Result.username_edit_available
    username_edit_labels = @($Result.username_edit_labels)
    owned_tab_closed = [bool]$Result.owned_tab_closed
    chrome_process_count_before = $ChromeBefore
    chrome_process_count_after = $ChromeAfter
    chrome_9222_before = $Chrome9222Before
    chrome_9222_after = $Chrome9222After
    chrome_side_effect = $ChromeSideEffect
    error = if ($Result.error) { [string]$Result.error } elseif ($ChromeSideEffect) { 'unexpected_chrome_side_effect' } else { $null }
}

$Output | ConvertTo-Json -Depth 6
if (-not $Output.ok) {
    exit 2
}
