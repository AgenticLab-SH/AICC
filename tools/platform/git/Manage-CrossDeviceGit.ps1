[CmdletBinding()]
param(
    [ValidateSet('Configure','Status','Commit','History','Pull','Push','Sync')][string]$Action = 'Status',
    [string]$Repository = (Get-Location).Path,
    [string]$RemoteName = 'origin',
    [ValidateSet('portable','win','mac')][string]$Scope = 'portable',
    [string]$Message,
    [ValidateSet('windows-x64','macos-arm64','both')][string]$TestedOn,
    [int]$MaxCount = 30
)

$ErrorActionPreference = 'Stop'
$repo = [IO.Path]::GetFullPath($Repository)
if (-not (Test-Path -LiteralPath (Join-Path $repo '.git'))) { throw "Not a Git working tree: $repo" }
if ($IsMacOS -and (Test-Path -LiteralPath '/opt/homebrew/bin')) {
    $env:PATH = "/opt/homebrew/bin$([IO.Path]::PathSeparator)$env:PATH"
}
$gitExe = (Get-Command git -CommandType Application -ErrorAction Stop | Select-Object -First 1).Source
function Git([Parameter(ValueFromRemainingArguments)][string[]]$Args) {
    $output = @(& $gitExe -C $repo @Args)
    if ($LASTEXITCODE -ne 0) { throw "git failed: $($Args -join ' ')" }
    return $output
}
function Get-Device {
    if ($IsWindows) { return 'windows' }
    if ($IsMacOS) { return 'macos' }
    throw 'Unsupported operating system.'
}
function Get-AiccStateRoot {
    if ($env:AICC_STATE_ROOT) { return [IO.Path]::GetFullPath($env:AICC_STATE_ROOT) }
    return [IO.Path]::GetFullPath((Join-Path $HOME '.ai-control-center'))
}

function Get-SyncState {
    Git fetch $RemoteName --prune | Out-Null
    $remoteRef = "$RemoteName/$branch"
    $counts = (([string](Git rev-list --left-right --count "HEAD...$remoteRef" | Select-Object -First 1)).Trim() -split '\s+')
    $dirty = @(& $gitExe -C $repo status --short)
    return [ordered]@{
        remote_ref = $remoteRef
        ahead = [int]$counts[0]
        behind = [int]$counts[1]
        dirty_entries = $dirty.Count
    }
}

function Invoke-FastForwardPull {
    $state = Get-SyncState
    if ($state.ahead -gt 0 -and $state.behind -gt 0) {
        throw "Local and $($state.remote_ref) have diverged; automatic merge is blocked."
    }
    if ($state.behind -eq 0) { return [ordered]@{operation='pull';result='already-current';state=$state} }
    if ($state.ahead -gt 0) { throw 'Local commits must be pushed before pulling.' }

    if ($state.dirty_entries -gt 0) {
        $dirtyPaths = @(& $gitExe -C $repo status --porcelain=v1 | ForEach-Object {
            if ($_.Length -ge 4) { ($_.Substring(3) -split ' -> ', 2)[-1].Trim('"') }
        } | Where-Object { $_ })
        $incomingPaths = @(Git diff --name-only "HEAD..$($state.remote_ref)")
        $overlap = @($dirtyPaths | Where-Object { $incomingPaths -contains $_ } | Sort-Object -Unique)
        if ($overlap.Count -gt 0) {
            throw "Pull would overlap $($overlap.Count) local dirty path(s); commit, stash, or reconcile them first."
        }
    }

    Git merge --ff-only $state.remote_ref | Out-Null
    $after = Get-SyncState
    if ($after.ahead -ne 0 -or $after.behind -ne 0) { throw 'Fast-forward pull did not converge to the remote.' }
    return [ordered]@{operation='pull';result='fast-forwarded';state=$after}
}

function Invoke-SafePush {
    $state = Get-SyncState
    if ($state.behind -gt 0) { throw "Remote has $($state.behind) commit(s) not present locally; pull first." }
    if ($state.ahead -eq 0) { return [ordered]@{operation='push';result='already-current';state=$state} }
    Git push $RemoteName "HEAD:refs/heads/$branch" | Out-Null
    $after = Get-SyncState
    if ($after.ahead -ne 0 -or $after.behind -ne 0) { throw 'Push did not converge to the remote.' }
    return [ordered]@{operation='push';result='pushed';state=$after}
}

$branch = ([string](Git branch --show-current | Select-Object -First 1)).Trim()
if (-not $branch) { throw 'Detached HEAD is not supported.' }
$remoteUrl = ([string](Git remote get-url $RemoteName | Select-Object -First 1)).Trim()

switch ($Action) {
    'Configure' {
        $remoteLine = @(Git ls-remote $RemoteName "refs/heads/$branch")
        if (-not $remoteLine.Count) { throw "Remote branch is missing: $RemoteName/$branch" }
        $remoteHead = ([string]$remoteLine[0] -split '\s+')[0]
        $localHead = ([string](Git rev-parse HEAD | Select-Object -First 1)).Trim()
        if ($remoteHead -ne $localHead) { throw "Local and $RemoteName/$branch HEAD differ; reconcile before configuring defaults." }
        Git config remote.pushDefault $RemoteName | Out-Null
        Git config push.default current | Out-Null
        Git config pull.ff only | Out-Null
        Git config fetch.prune true | Out-Null
        Git config "branch.$branch.remote" $RemoteName | Out-Null
        Git config "branch.$branch.merge" "refs/heads/$branch" | Out-Null
        Git config "branch.$branch.pushRemote" $RemoteName | Out-Null
        [ordered]@{action='configure';repo=$repo;branch=$branch;head=$localHead;remote=$RemoteName;remote_url=$remoteUrl;other_remotes_unchanged=$true} | ConvertTo-Json -Compress
    }
    'Status' {
        $state = Get-SyncState
        $head = ([string](Git rev-parse HEAD | Select-Object -First 1)).Trim()
        [ordered]@{action='status';repo=$repo;branch=$branch;head=$head;remote_ref=$state.remote_ref;ahead=$state.ahead;behind=$state.behind;dirty_entries=$state.dirty_entries;safe_to_fast_forward=($state.ahead-eq0-and$state.behind-ge0)} | ConvertTo-Json -Compress
    }
    'Commit' {
        if ([string]::IsNullOrWhiteSpace($Message)) { throw '-Message is required for Commit.' }
        & $gitExe -C $repo diff --cached --quiet
        if ($LASTEXITCODE -eq 0) { throw 'No staged changes. This tool never stages files automatically.' }
        $device = Get-Device
        if (-not $TestedOn) { $TestedOn = if ($device -eq 'windows') { 'windows-x64' } else { 'macos-arm64' } }
        $impact = switch ($Scope) { 'portable' {'portable'} 'win' {'windows-only'} 'mac' {'macos-only'} }
        $title = "$Scope`: $Message"
        $trailers = "Source-Device: $device`nTested-On: $TestedOn`nCross-Device-Impact: $impact"
        Git commit -m $title -m $trailers | Out-Null
        $head = ([string](Git rev-parse HEAD | Select-Object -First 1)).Trim()
        $ledgerDir = Join-Path (Get-AiccStateRoot) 'cross-device/ledgers/git'
        New-Item -ItemType Directory -Force -Path $ledgerDir | Out-Null
        $record = [ordered]@{timestamp=(Get-Date).ToString('o');device=$device;repo=$repo;branch=$branch;head=$head;scope=$Scope;tested_on=$TestedOn;message=$Message}
        Add-Content -LiteralPath (Join-Path $ledgerDir "$device.jsonl") -Value ($record | ConvertTo-Json -Compress) -Encoding utf8NoBOM
        [ordered]@{action='commit';repo=$repo;branch=$branch;head=$head;title=$title;ledger=(Join-Path $ledgerDir "$device.jsonl")} | ConvertTo-Json -Compress
    }
    'History' {
        $device = Get-Device
        $rows = @(Git log "--max-count=$MaxCount" '--format=%H%x09%aI%x09%s%x09%(trailers:key=Source-Device,valueonly)')
        [ordered]@{action='history';repo=$repo;device=$device;entries=$rows} | ConvertTo-Json -Depth 4
    }
    'Pull' {
        $result = Invoke-FastForwardPull
        [ordered]@{action='pull';repo=$repo;branch=$branch;remote=$RemoteName;result=$result.result;state=$result.state} | ConvertTo-Json -Depth 4 -Compress
    }
    'Push' {
        $result = Invoke-SafePush
        [ordered]@{action='push';repo=$repo;branch=$branch;remote=$RemoteName;result=$result.result;state=$result.state} | ConvertTo-Json -Depth 4 -Compress
    }
    'Sync' {
        $state = Get-SyncState
        if ($state.ahead -gt 0 -and $state.behind -gt 0) { throw 'Local and remote histories diverged; automatic sync is blocked.' }
        if ($state.ahead -gt 0) { $result = Invoke-SafePush }
        elseif ($state.behind -gt 0) { $result = Invoke-FastForwardPull }
        else { $result = [ordered]@{operation='none';result='already-current';state=$state} }
        [ordered]@{action='sync';repo=$repo;branch=$branch;remote=$RemoteName;operation=$result.operation;result=$result.result;state=$result.state} | ConvertTo-Json -Depth 4 -Compress
    }
}
