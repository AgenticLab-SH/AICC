[CmdletBinding()]
param(
  [Parameter(Mandatory=$true, ValueFromPipeline=$true)][string]$Message,
  [switch]$MarkdownV2,
  [string]$EnvFile = ''
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8

$aiccStateRoot = if ($env:AICC_STATE_ROOT) { $env:AICC_STATE_ROOT } else { Join-Path $HOME '.ai-control-center' }
if (-not $EnvFile) {
  $EnvFile = if ($env:AICC_TELEGRAM_ENV_FILE) { $env:AICC_TELEGRAM_ENV_FILE } else { Join-Path $aiccStateRoot 'telegram/agent-bridge.env' }
}
if (-not (Test-Path -LiteralPath $EnvFile -PathType Leaf)) {
  throw "Telegram configuration was not found: $EnvFile"
}

$config = @{}
foreach ($line in Get-Content -LiteralPath $EnvFile -Encoding UTF8) {
  if ($line -match '^\s*([A-Z][A-Z0-9_]*)\s*=\s*["'']?([^"'']*)["'']?\s*$') {
    $config[$Matches[1]] = $Matches[2].Trim()
  }
}
$token = @($env:TELEGRAM_BOT_TOKEN, $config['TELEGRAM_BOT_TOKEN'], $config['CODEX_TELEGRAM_BOT_TOKEN'], $config['GEMINI_CONNECT_TELEGRAM_BOT_TOKEN']) | Where-Object { $_ } | Select-Object -First 1
$chatId = @($env:TELEGRAM_CHAT_ID, $config['TELEGRAM_CHAT_ID'], $config['CODEX_TELEGRAM_CHAT_ID'], $config['TELEGRAM_ALLOWED_USERS']) | Where-Object { $_ } | Select-Object -First 1
if ($chatId) { $chatId = ([string]$chatId -split ',')[0].Trim() }
if (-not $token -or -not $chatId) { throw 'Telegram route is incomplete.' }

$body = @{ chat_id = $chatId; text = $Message }
if ($MarkdownV2) { $body['parse_mode'] = 'MarkdownV2' }
try {
  $json = $body | ConvertTo-Json -Compress
  $bytes = [Text.Encoding]::UTF8.GetBytes($json)
  Invoke-RestMethod -Method Post -Uri "https://api.telegram.org/bot$token/sendMessage" -ContentType 'application/json; charset=utf-8' -Body $bytes | Out-Null
  [pscustomobject]@{ ok = $true; status = 'sent' } | ConvertTo-Json -Compress
} catch {
  throw "Telegram send failed: $($_.Exception.GetType().Name)"
}
