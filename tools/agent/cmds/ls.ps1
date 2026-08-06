# cmds/ls.ps1 — `agent ls` 통합 세션 목록 (시간순, 모든 에이전트)
param(
    [Parameter(Position=0)][int]$Top = 20,
    [ValidateSet('all','claude','codex')][string]$Source = 'all'
)
$root = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
. (Join-Path $root 'lib\sessions.ps1')
$script:UserHome = [Environment]::GetFolderPath([Environment+SpecialFolder]::UserProfile)

function script:_Ago([datetime]$ts) {
    $delta = (Get-Date) - $ts
    if ($delta.TotalMinutes -lt 1)  { return 'just now' }
    if ($delta.TotalMinutes -lt 60) { return ('{0}m ago' -f [int]$delta.TotalMinutes) }
    if ($delta.TotalHours -lt 24)   { return ('{0}h ago' -f [int]$delta.TotalHours) }
    if ($delta.TotalDays -lt 7)     { return ('{0}d ago' -f [int]$delta.TotalDays) }
    return $ts.ToString('MM-dd')
}

function script:_ShortCwd([string]$cwd) {
    if (-not $cwd) { return '?' }
    $shrunk = $cwd -replace [Regex]::Escape($script:UserHome), '~'
    if ($shrunk.Length -le 36) { return $shrunk }
    return $shrunk.Substring(0, 12) + [char]0x2026 + $shrunk.Substring($shrunk.Length - 22)
}

function script:_AgentColor([string]$src) {
    if ($src -eq 'claude') { return 'Magenta' }
    if ($src -eq 'codex')  { return 'Green' }
    return 'White'
}

$sessions = @(Get-AgentSession -Source $Source -Top $Top)

if ($sessions.Count -eq 0) {
    Write-Host ""
    Write-Host "  No sessions found." -ForegroundColor DarkGray
    Write-Host ""
    return
}

Write-Host ""
Write-Host ("  {0,-4} {1,-7} {2,-10} {3,-36} {4}" -f '#', 'Agent', 'Time', 'Project', 'Preview') -ForegroundColor DarkGray
Write-Host ("  " + ('-' * 90)) -ForegroundColor DarkGray

$i = 0
foreach ($s in $sessions) {
    $i++
    $num = ('{0,4}' -f $i)
    $agent = ('{0,-7}' -f $s.Source)
    $time = ('{0,-10}' -f (script:_Ago $s.Mtime))
    $proj = ('{0,-36}' -f (script:_ShortCwd $s.Cwd))
    $preview = $s.Preview
    if ($preview.Length -gt 40) { $preview = $preview.Substring(0, 39) + [char]0x2026 }

    Write-Host "  $num " -NoNewline
    Write-Host $agent -NoNewline -ForegroundColor (script:_AgentColor $s.Source)
    Write-Host " $time $proj " -NoNewline
    Write-Host $preview -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  Tip: agent resume" -ForegroundColor DarkGray
Write-Host ""
