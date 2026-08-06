# Deploy AICC-managed guidance skills to selected agent homes.

[CmdletBinding(SupportsShouldProcess = $true)]
param(
    [Alias('Hub')][string]$AiccRoot = (Join-Path $PSScriptRoot '../../..'),
    [string]$CatalogPath = '',
    [string[]]$TargetGroups = @(),
    [switch]$AllTargets,
    [string[]]$SkillNames = @(),
    [switch]$Plan,
    [switch]$PruneManaged,
    [switch]$RetireSelectedTargets,
    [switch]$AsJson
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

if (-not (Test-Path -LiteralPath $AiccRoot -PathType Container)) {
    $candidates = @($env:AICC_ROOT, (Join-Path $PSScriptRoot '../../..')) | Where-Object { $_ }
    $AiccRoot = @($candidates | Where-Object { Test-Path -LiteralPath (Join-Path $_ 'guidance/skills') -PathType Container } | Select-Object -First 1)
}
if (-not $AiccRoot) { throw 'Canonical AICC root was not found.' }
$AiccRoot = (Resolve-Path -LiteralPath $AiccRoot).Path
$activeRoot = Join-Path $AiccRoot 'guidance/skills'
$modulePath = Join-Path $AiccRoot 'tools/platform/core/AgentHomeDeployment.psm1'
if (-not (Test-Path -LiteralPath $activeRoot -PathType Container)) { throw "Missing active skill root: $activeRoot" }
if (-not (Test-Path -LiteralPath $modulePath -PathType Leaf)) { throw "Missing deployment module: $modulePath" }
Import-Module $modulePath -Force

if (-not $CatalogPath) { $CatalogPath = Join-Path $AiccRoot 'guidance/config/agent-catalog.toml' }
function Get-SkillSourceMap {
    param([string]$Root)
    $map = @{}
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return $map }
    foreach ($dir in Get-ChildItem -LiteralPath $Root -Directory -ErrorAction SilentlyContinue) {
        $skillMd = Join-Path $dir.FullName 'SKILL.md'
        if (Test-Path -LiteralPath $skillMd -PathType Leaf) { $map[$dir.Name] = $dir.FullName }
    }
    return $map
}

function Get-DirectoryFileInventory {
    param([Parameter(Mandatory)][string]$Root)
    if (-not (Test-Path -LiteralPath $Root -PathType Container)) { return @() }
    return @(Get-ChildItem -LiteralPath $Root -Recurse -File -Force -ErrorAction SilentlyContinue |
        Where-Object { -not (Test-SkillDeploymentFileExcluded -Root $Root -Path $_.FullName) } |
        ForEach-Object {
        $relative = [System.IO.Path]::GetRelativePath($Root, $_.FullName) -replace '\\', '/'
        [ordered]@{ path = $relative; sha256 = (Get-FileHash -Algorithm SHA256 -LiteralPath $_.FullName).Hash; bytes = $_.Length }
    })
}

function Test-SkillDeploymentFileExcluded {
    param([Parameter(Mandatory)][string]$Root, [Parameter(Mandatory)][string]$Path)
    $relative = [System.IO.Path]::GetRelativePath($Root, $Path) -replace '\\', '/'
    return (
        $relative -match '(^|/)(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache)(/|$)' -or
        $relative -match '(?i)\.(pyc|pyo)$' -or
        $relative -match '(^|/)\.DS_Store$'
    )
}

function Read-DeploymentManifest {
    param([string]$Path)
    if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { return $null }
    try { return (Get-Content -LiteralPath $Path -Raw -Encoding UTF8 | ConvertFrom-Json) } catch { throw "Invalid deployment manifest: $Path - $($_.Exception.Message)" }
}

function Test-ManifestOwnsSkill {
    param($Manifest, [string]$Name)
    if ($null -eq $Manifest) { return $false }
    return [bool](@($Manifest.managed_skills | Where-Object { $_.name -eq $Name }).Count)
}

function Test-SourceHashMatch {
    param([string]$TargetDir, [string]$SourceDir)
    $targetMd = Join-Path $TargetDir 'SKILL.md'
    $sourceMd = Join-Path $SourceDir 'SKILL.md'
    if (-not (Test-Path -LiteralPath $targetMd -PathType Leaf) -or -not (Test-Path -LiteralPath $sourceMd -PathType Leaf)) { return $false }
    return (Get-FileHash -Algorithm SHA256 -LiteralPath $targetMd).Hash -eq (Get-FileHash -Algorithm SHA256 -LiteralPath $sourceMd).Hash
}

function Write-Utf8NoBom {
    param([Parameter(Mandatory)][string]$Path, [Parameter(Mandatory)][string]$Content)
    [System.IO.File]::WriteAllText($Path, $Content, [System.Text.UTF8Encoding]::new($false))
}

function Copy-ManagedSkill {
    param([Parameter(Mandatory)][string]$SourceDir, [Parameter(Mandatory)][string]$DestinationDir)
    if (Test-Path -LiteralPath $DestinationDir) { Remove-Item -LiteralPath $DestinationDir -Recurse -Force }
    New-Item -ItemType Directory -Force -Path $DestinationDir | Out-Null
    $sourceMd = Join-Path $SourceDir 'SKILL.md'
    $bytes = [System.IO.File]::ReadAllBytes($sourceMd)
    $text = if ($bytes.Length -ge 3 -and $bytes[0] -eq 0xEF -and $bytes[1] -eq 0xBB -and $bytes[2] -eq 0xBF) {
        [System.Text.Encoding]::UTF8.GetString($bytes, 3, $bytes.Length - 3)
    } else {
        [System.Text.Encoding]::UTF8.GetString($bytes)
    }
    if (-not $text.StartsWith('---')) { throw "Skill markdown missing YAML frontmatter: $sourceMd" }
    Write-Utf8NoBom -Path (Join-Path $DestinationDir 'SKILL.md') -Content $text
    foreach ($childName in @('agents', 'assets', 'references', 'scripts', 'batches')) {
        $sourceChild = Join-Path $SourceDir $childName
        if (Test-Path -LiteralPath $sourceChild -PathType Container) {
            foreach ($sourceFile in Get-ChildItem -LiteralPath $sourceChild -Recurse -File -Force -ErrorAction SilentlyContinue) {
                if (Test-SkillDeploymentFileExcluded -Root $SourceDir -Path $sourceFile.FullName) { continue }
                $relative = [System.IO.Path]::GetRelativePath($SourceDir, $sourceFile.FullName)
                $destinationFile = Join-Path $DestinationDir $relative
                $destinationParent = Split-Path -Parent $destinationFile
                New-Item -ItemType Directory -Force -Path $destinationParent | Out-Null
                Copy-Item -LiteralPath $sourceFile.FullName -Destination $destinationFile -Force
            }
        }
    }
}

$policy = Get-AgentHomeDeploymentPolicy -AiccRoot $AiccRoot -CatalogPath $CatalogPath
$selectedGroups = @(Select-AgentHomeDeploymentTargets -Policy $policy -TargetGroups $TargetGroups -AllTargets:$AllTargets)
$selectedSkillRoots = @($selectedGroups | ForEach-Object skills | Sort-Object -Unique)
if ($selectedSkillRoots.Count -eq 0) { throw 'Selected deployment groups have no skill roots.' }
foreach ($root in $selectedSkillRoots) {
    if (-not (Test-AgentHomeDeploymentDescendant -Root $policy.user_home -Path $root)) { throw "Skill target escapes the user home: $root" }
    $parent = Split-Path -Parent $root
    if (-not (Test-Path -LiteralPath $parent -PathType Container)) { throw "Skill target parent does not exist: $parent" }
    if (Test-Path -LiteralPath $root) {
        $item = Get-Item -LiteralPath $root -Force
        if ($item.Attributes -band [System.IO.FileAttributes]::ReparsePoint) { throw "Refusing a symlink/reparse skill target: $root" }
    } elseif (-not $RetireSelectedTargets -and -not $Plan -and $PSCmdlet.ShouldProcess($root, 'Create selected skill target')) {
        New-Item -ItemType Directory -Force -Path $root | Out-Null
    }
}

$activeMap = Get-SkillSourceMap -Root $activeRoot

$requestedNames = @($SkillNames | Where-Object { $_ } | Sort-Object -Unique)
$unknownRequested = @($requestedNames | Where-Object { -not $activeMap.ContainsKey($_) })
if ($unknownRequested.Count -gt 0) { throw "Unknown skill names: $($unknownRequested -join ', ')" }
$deployNames = @($activeMap.Keys | Where-Object { $requestedNames.Count -eq 0 -or $_ -in $requestedNames } | Sort-Object)

$actions = @()
$refused = @()
$manifestsWritten = @()
foreach ($group in $selectedGroups) {
    foreach ($root in $group.skills) {
        $manifestPath = Join-Path $root $policy.manifest_name
        $manifest = Read-DeploymentManifest -Path $manifestPath
        $legacyManifestPaths = @($policy.legacy_manifest_names | ForEach-Object { Join-Path $root $_ })
        if (-not $manifest) {
            foreach ($legacyPath in $legacyManifestPaths) {
                $legacyManifest = Read-DeploymentManifest -Path $legacyPath
                if ($legacyManifest) { $manifest = $legacyManifest; break }
            }
        }
        $managedEntries = @()

        if ($RetireSelectedTargets) {
            if (-not (Test-Path -LiteralPath $root -PathType Container)) { continue }
            foreach ($destination in Get-ChildItem -LiteralPath $root -Directory -Force -ErrorAction SilentlyContinue) {
                $name = $destination.Name
                $sourceDir = if ($activeMap.ContainsKey($name)) { $activeMap[$name] } else { '' }
                if (-not $sourceDir) { continue }
                $owned = (Test-ManifestOwnsSkill -Manifest $manifest -Name $name) -or (Test-SourceHashMatch -TargetDir $destination.FullName -SourceDir $sourceDir)
                if (-not $owned) {
                    $refused += [ordered]@{ group = $group.id; root = $root; skill = $name; action = 'retire'; reason = 'unowned-or-modified' }
                    continue
                }
                $actions += [ordered]@{ group = $group.id; root = $root; skill = $name; action = 'retire' }
                if (-not $Plan -and $PSCmdlet.ShouldProcess($destination.FullName, 'Retire AICC-managed skill from optional target')) {
                    Remove-Item -LiteralPath $destination.FullName -Recurse -Force
                }
            }
            if (Test-Path -LiteralPath $manifestPath -PathType Leaf) {
                $actions += [ordered]@{ group = $group.id; root = $root; action = 'retire-manifest'; path = $manifestPath }
                if (-not $Plan -and $PSCmdlet.ShouldProcess($manifestPath, 'Remove retired deployment manifest')) {
                    Remove-Item -LiteralPath $manifestPath -Force
                }
            }
            continue
        }

        if ($PruneManaged) {
            $staleManaged = if ($manifest) {
                @($manifest.managed_skills | ForEach-Object { [string]$_.name } | Where-Object { $_ -and -not $activeMap.ContainsKey($_) })
            } else { @() }
            $rootPruneCandidates = @($staleManaged | Sort-Object -Unique)
            foreach ($name in $rootPruneCandidates) {
                $destination = Join-Path $root $name
                if (-not (Test-Path -LiteralPath $destination -PathType Container)) { continue }
                $sourceDir = if ($activeMap.ContainsKey($name)) { $activeMap[$name] } else { '' }
                $owned = (Test-ManifestOwnsSkill -Manifest $manifest -Name $name) -or ($sourceDir -and (Test-SourceHashMatch -TargetDir $destination -SourceDir $sourceDir))
                if (-not $owned) {
                    $refused += [ordered]@{ group = $group.id; root = $root; skill = $name; action = 'prune'; reason = 'unowned-or-modified' }
                    continue
                }
                $actions += [ordered]@{ group = $group.id; root = $root; skill = $name; action = 'prune' }
                if (-not $Plan -and $PSCmdlet.ShouldProcess($destination, 'Remove stale manifest-owned AICC skill')) {
                    Remove-Item -LiteralPath $destination -Recurse -Force
                }
            }
        }

        foreach ($name in $deployNames) {
            $sourceDir = [string]$activeMap[$name]
            $destination = Join-Path $root $name
            $actions += [ordered]@{ group = $group.id; root = $root; skill = $name; action = if (Test-Path -LiteralPath $destination) { 'update' } else { 'create' } }
            if (-not $Plan -and $PSCmdlet.ShouldProcess($destination, "Deploy AICC skill $name")) {
                Copy-ManagedSkill -SourceDir $sourceDir -DestinationDir $destination
            }
            $sourceHash = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $sourceDir 'SKILL.md')).Hash
            $files = if ($Plan) { Get-DirectoryFileInventory -Root $sourceDir } else { Get-DirectoryFileInventory -Root $destination }
            $managedEntries += [ordered]@{ name = $name; source = $sourceDir; source_skill_sha256 = $sourceHash; files = $files }
        }

        if (-not $Plan) {
            $preserved = @()
            if ($manifest) {
                $preserved = @($manifest.managed_skills | Where-Object {
                    $_.name -notin $deployNames -and (Test-Path -LiteralPath (Join-Path $root $_.name) -PathType Container)
                })
            }
            $manifestBody = [ordered]@{
                schema_version = 1
                target_group = $group.id
                aicc_root = $AiccRoot
                generated_at = (Get-Date).ToString('o')
                deployment_mode = if ($requestedNames.Count) { 'partial' } else { 'full' }
                requested_skills = $requestedNames
                managed_skills = @($preserved + $managedEntries | Sort-Object { [string]$_.name } -Unique)
            } | ConvertTo-Json -Depth 8
            if ($PSCmdlet.ShouldProcess($manifestPath, 'Write AICC guidance deployment manifest')) {
                Write-Utf8NoBom -Path $manifestPath -Content ($manifestBody + "`n")
                $manifestsWritten += $manifestPath
                foreach ($legacyPath in $legacyManifestPaths) {
                    if (Test-Path -LiteralPath $legacyPath -PathType Leaf) { Remove-Item -LiteralPath $legacyPath -Force }
                }
            }
        }
    }
}

[pscustomobject]@{
    status = if ($Plan) { 'planned' } else { 'ok' }
    dry_run = [bool]$Plan
    aicc_root = $AiccRoot
    catalog_path = $policy.catalog_path
    default_groups = $policy.default_groups
    selected_groups = @($selectedGroups.id)
    selected_skill_roots = $selectedSkillRoots
    deployed_skills = $deployNames
    prune_managed = [bool]$PruneManaged
    retire_selected_targets = [bool]$RetireSelectedTargets
    actions = $actions
    refused = $refused
    manifests_written = $manifestsWritten
} | ConvertTo-Json -Compress -Depth 9
