#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)]
    [ValidateSet('List','Create','Delete')]
    [string]$Action,

    [string]$Endpoint = '',
    [string]$DisplayName = 'AI Control',
    [string[]]$UsernameCandidate = @(),
    [string]$CredentialFile = '',
    [string]$PreserveFrom = '',
    [string[]]$BotUsername = @(),
    [ValidateRange(10,300)]
    [int]$TimeoutSec = 60
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$AiccRoot = (Resolve-Path -LiteralPath (Join-Path $PSScriptRoot '..\..\..')).Path
$CoordinationReader = Join-Path $AiccRoot 'tools\platform\core\Read-AiccCoordination.ps1'
$IdentityGuard = Join-Path $AiccRoot 'tools\platform\web-automation\Assert-CdpEndpointIdentity.ps1'
$Manager = Join-Path $PSScriptRoot 'botfather_manager.py'

if (-not $Endpoint) {
    $Endpoint = [string](& $CoordinationReader -Key browser.cdp_whale_url)
}
if (-not $Endpoint) { throw 'cdp_whale_endpoint_missing' }
$ExpectedProfile = [string](& $CoordinationReader -Key browser.cdp_whale_profile_dir)
& $IdentityGuard -ExpectedBrowser whale -Endpoint $Endpoint -ExpectedProfileDir $ExpectedProfile | Out-Null
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$Arguments = @($Manager, '--endpoint', $Endpoint, '--timeout-sec', [string]$TimeoutSec)
switch ($Action) {
    'List' { $Arguments += 'list' }
    'Create' {
        if (-not $UsernameCandidate -or -not $CredentialFile) { throw 'create_requires_username_candidates_and_credential_file' }
        $Arguments += @('create','--display-name',$DisplayName,'--credential-file',$CredentialFile)
        if ($PreserveFrom) { $Arguments += @('--preserve-from',$PreserveFrom) }
        foreach ($Candidate in $UsernameCandidate) { $Arguments += @('--username',$Candidate) }
    }
    'Delete' {
        if (-not $BotUsername) { throw 'delete_requires_valid_bot_username' }
        $Arguments += 'delete'
        foreach ($Username in $BotUsername) {
            if ($Username -notmatch '^@[A-Za-z0-9_]{5,32}$') { throw 'delete_requires_valid_bot_username' }
            $Arguments += @('--bot-username',$Username)
        }
    }
}

$ChromeBefore = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
$PortBefore = [bool](Get-NetTCPConnection -State Listen -LocalPort 9222 -ErrorAction SilentlyContinue)
$Raw = & python @Arguments
$ExitCode = $LASTEXITCODE
$ChromeAfter = @(Get-Process chrome -ErrorAction SilentlyContinue).Count
$PortAfter = [bool](Get-NetTCPConnection -State Listen -LocalPort 9222 -ErrorAction SilentlyContinue)
$SideEffect = ($ChromeAfter -gt $ChromeBefore) -or (-not $PortBefore -and $PortAfter)

try { $Result = $Raw | ConvertFrom-Json -ErrorAction Stop }
catch { $Result = [pscustomobject]@{ok=$false;error='invalid_manager_json';token_exposed=$false}; $ExitCode = 2 }

$Result | Add-Member -NotePropertyName chrome_side_effect -NotePropertyValue $SideEffect -Force
$Result | Add-Member -NotePropertyName chrome_process_count_before -NotePropertyValue $ChromeBefore -Force
$Result | Add-Member -NotePropertyName chrome_process_count_after -NotePropertyValue $ChromeAfter -Force
$Result | ConvertTo-Json -Depth 7
if ($ExitCode -ne 0 -or $SideEffect -or -not $Result.ok) { exit 2 }
