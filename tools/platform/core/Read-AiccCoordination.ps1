#requires -Version 7.0
[CmdletBinding()]
param(
    [Parameter(Mandatory)][string]$Key,
    [string]$Path = (Join-Path $HOME '.ai-control-center/guidance/coordination.toml')
)

$ErrorActionPreference = 'Stop'
if (-not (Test-Path -LiteralPath $Path -PathType Leaf)) { throw "Private coordination file not found: $Path" }
$parts = ($Key -replace '-', '.').Split('.', 2)
if ($parts.Count -ne 2) { throw "Key must be section.key: $Key" }
$section = ''
foreach ($raw in Get-Content -LiteralPath $Path -Encoding UTF8) {
    $line = $raw.Trim()
    if (-not $line -or $line.StartsWith('#')) { continue }
    if ($line -match '^\[(?<name>[^\]]+)\]$') { $section = $Matches.name.Trim(); continue }
    if ($section -ne $parts[0] -or $line -notmatch '^(?<key>[A-Za-z0-9_]+)\s*=\s*(?<value>.+?)\s*$') { continue }
    if ($Matches.key -ne $parts[1]) { continue }
    $value = $Matches.value
    if ($value -match '^"(?<text>(?:[^"\\]|\\.)*)"\s*(#.*)?$') { $Matches.text; return }
    $comment = $value.IndexOf('#')
    if ($comment -ge 0) { $value = $value.Substring(0, $comment).Trim() }
    $value.Trim('"').Trim("'"); return
}
throw "Coordination key not found: $Key"
