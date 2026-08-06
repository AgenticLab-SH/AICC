# Validate bounded Codex/Claude-default agent-home deployment policy and dry-run behavior.

[CmdletBinding()]
param(
    [Alias('Hub')][string]$AiccRoot = '',
    [switch]$AsJson,
    [switch]$SummaryOnly
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
if (-not $AiccRoot) { $AiccRoot = Join-Path $PSScriptRoot '../../..' }
$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$modulePath = Join-Path $AiccRoot 'tools/platform/core/AgentHomeDeployment.psm1'
Import-Module $modulePath -Force

$checks = @()
function Add-Check {
    param([string]$Name, [bool]$Ok, [string]$Detail = '')
    $script:checks += [pscustomobject]@{ name=$Name; ok=$Ok; detail=$Detail }
}

$policy = Get-AgentHomeDeploymentPolicy -AiccRoot $AiccRoot
$defaults = @(Select-AgentHomeDeploymentTargets -Policy $policy)
$all = @(Select-AgentHomeDeploymentTargets -Policy $policy -AllTargets)
Add-Check 'default groups are exactly Codex and Claude' (
    @($defaults.id).Count -eq 2 -and 'codex' -in $defaults.id -and 'claude' -in $defaults.id
) ($defaults.id -join ', ')
Add-Check 'catalog exposes only Codex and Claude deployment groups' (
    $all.Count -eq 2 -and 'codex' -in $all.id -and 'claude' -in $all.id
) ($all.id -join ', ')
Add-Check 'default targets expose two skill roots' (@($defaults.skills).Count -eq 2) ([string]@($defaults.skills).Count)
Add-Check 'default targets expose three directive files' (@($defaults.rules).Count -eq 3) ([string]@($defaults.rules).Count)
Add-Check 'all target rule/generated pairs align' (@($all | Where-Object { $_.rules.Count -ne $_.generated.Count }).Count -eq 0)

$userHome = $policy.user_home
foreach ($target in $all) {
    foreach ($path in @($target.skills + $target.rules)) {
        Add-Check "$($target.id) home target is bounded: $path" (Test-AgentHomeDeploymentDescendant -Root $userHome -Path $path)
    }
    foreach ($path in $target.generated) {
        Add-Check "$($target.id) generated target is bounded: $path" (Test-AgentHomeDeploymentDescendant -Root $AiccRoot -Path $path)
    }
}

$unknownRejected = $false
try { Select-AgentHomeDeploymentTargets -Policy $policy -TargetGroups @('unknown-agent') | Out-Null } catch { $unknownRejected = $true }
Add-Check 'unknown target group is rejected' $unknownRejected

$skillPlanRaw = @(& pwsh -NoProfile -File (Join-Path $AiccRoot 'tools/platform/core/deploy_active_skills.ps1') -AiccRoot $AiccRoot -Plan -AsJson) -join "`n"
$skillPlan = $skillPlanRaw | ConvertFrom-Json
Add-Check 'skill deploy dry-run selects only defaults' (
    @($skillPlan.selected_groups).Count -eq 2 -and 'codex' -in $skillPlan.selected_groups -and 'claude' -in $skillPlan.selected_groups
) ($skillPlan.selected_groups -join ', ')
Add-Check 'skill deploy dry-run performs no writes' ([bool]$skillPlan.dry_run) ([string]$skillPlan.status)
Add-Check 'full skill deploy plan has no requested subset' (@($skillPlan.deployed_skills).Count -gt 0) ("skills={0}" -f @($skillPlan.deployed_skills).Count)

$skillDeployerText = Get-Content -LiteralPath (Join-Path $AiccRoot 'tools/platform/core/deploy_active_skills.ps1') -Raw -Encoding UTF8
Add-Check 'skill deployment excludes runtime caches from copies and manifests' (
    $skillDeployerText -match 'Test-SkillDeploymentFileExcluded' -and
    $skillDeployerText -match '__pycache__' -and
    $skillDeployerText -match '\\.\(pyc\|pyo\)' -and
    $skillDeployerText -match '\\.DS_Store'
) 'cache filters are applied by copy and inventory paths'

$skillInspectorText = Get-Content -LiteralPath (Join-Path $AiccRoot 'tools/platform/inspect/Inspect-AgentSkills.ps1') -Raw -Encoding UTF8
Add-Check 'skill inspection compares full trees and manifest file inventories' (
    $skillInspectorText -match 'Compare-SkillTrees' -and
    $skillInspectorText -match 'Get-SkillTreeInventory' -and
    $skillInspectorText -match 'manifest file inventory mismatch'
) 'source, deployed target, and manifest files are path/hash/size checked'

$mixedManifestEntries = @(
    [pscustomobject]@{ name = 'preserved-skill' },
    [ordered]@{ name = 'updated-skill' },
    [pscustomobject]@{ name = 'preserved-skill' }
)
$mixedManifestNames = @($mixedManifestEntries | Sort-Object { [string]$_.name } -Unique | ForEach-Object { [string]$_.name })
Add-Check 'partial skill manifest sort preserves mixed object entries' (
    $mixedManifestNames.Count -eq 2 -and
    'preserved-skill' -in $mixedManifestNames -and
    'updated-skill' -in $mixedManifestNames
) ($mixedManifestNames -join ', ')

$directivePlanRaw = @(& pwsh -NoProfile -File (Join-Path $AiccRoot 'tools/platform/core/deploy_directives.ps1') -AiccRoot $AiccRoot -Plan -AsJson) -join "`n"
$directivePlan = $directivePlanRaw | ConvertFrom-Json
Add-Check 'directive deploy dry-run selects only defaults' (
    @($directivePlan.selected_groups).Count -eq 2 -and 'codex' -in $directivePlan.selected_groups -and 'claude' -in $directivePlan.selected_groups
) ($directivePlan.selected_groups -join ', ')
Add-Check 'directive deploy dry-run performs no writes' ([bool]$directivePlan.dry_run) ([string]$directivePlan.status)

$failed = @($checks | Where-Object { -not $_.ok })
$result = [ordered]@{
    ok = ($failed.Count -eq 0)
    default_groups = @($defaults.id)
    all_groups = @($all.id)
    check_count = $checks.Count
    failed_count = $failed.Count
    checks = @($checks)
}
if ($SummaryOnly) {
    $result = [ordered]@{
        ok = ($failed.Count -eq 0)
        default_groups = @($defaults.id)
        all_groups = @($all.id)
        check_count = $checks.Count
        failed_count = $failed.Count
        failed_checks = @($failed | Select-Object -First 20)
    }
}
if ($AsJson) { $result | ConvertTo-Json -Compress -Depth 7 } else { $result | ConvertTo-Json -Depth 7 }
if (-not $result.ok) { exit 1 }
