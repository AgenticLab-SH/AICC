# Read-only active skill inventory.
param([switch]$Json)

$ErrorActionPreference = 'Stop'
$AiccRoot = Split-Path -Parent (Split-Path -Parent (Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)))
$root = Join-Path $AiccRoot 'guidance/skills'
$items = @(Get-ChildItem -LiteralPath $root -Directory | ForEach-Object {
    $skillFile = Join-Path $_.FullName 'SKILL.md'
    if (-not (Test-Path -LiteralPath $skillFile -PathType Leaf)) { return }
    $raw = Get-Content -LiteralPath $skillFile -Raw -Encoding UTF8
    $name = if ($raw -match '(?m)^name:\s*(.+)$') { $Matches[1].Trim() } else { $_.Name }
    $description = if ($raw -match '(?m)^description:\s*(.+)$') { $Matches[1].Trim() } else { '' }
    [pscustomobject]@{ name=$name; description=$description; path=$_.FullName }
} | Sort-Object name)

$result = [ordered]@{ ok=$true; count=$items.Count; skills=$items }
if ($Json) { $result | ConvertTo-Json -Depth 4; return }
Write-Host ''
Write-Host "Active skills ($($items.Count))" -ForegroundColor Cyan
foreach ($item in $items) {
    Write-Host ("  {0,-30} {1}" -f $item.name, $item.description)
}
Write-Host ''
