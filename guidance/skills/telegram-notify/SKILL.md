---
name: telegram-notify
description: Send an authorized Telegram completion, alert, or user-response request, and coordinate one correlation-bound readiness or one-time-code reply when another skill explicitly requires Telegram input. Not for general chat, unsolicited progress, or owning the website login workflow.
---

# Telegram notify

## Overview
Send an authorized completion or alert through the credential reference at
`~/.ai-control-center/telegram/agent-bridge.env`. Never print, copy, or hardcode
the token or chat ID.

## When to use
- The user explicitly asks for a Telegram message.
- A long-running background task completes and a notification was expected.
- A critical failure requires attention.
- Another skill explicitly requires the user to confirm readiness or return a
  short-lived verification code through Telegram.

## Usage
Run the helper script using PowerShell, passing your message string to the `-Message` parameter.

```powershell
pwsh -NoProfile -File "$HOME/.codex/skills/telegram-notify/scripts/send_telegram_message.ps1" -Message "Your message here"
```

## Verification responses

Use the canonical helper only as transport for a workflow such as
`complete-site-login`. It permits one active request, stores only correlation
state in a private temporary directory, and never persists the returned code.

```bash
python3 "$HOME/.codex/skills/telegram-notify/scripts/telegram_verification.py" start --site "Example" --expiry-minutes 5
python3 "$HOME/.codex/skills/telegram-notify/scripts/telegram_verification.py" poll-ready --request-id <id> --wait-seconds 45
python3 "$HOME/.codex/skills/telegram-notify/scripts/telegram_verification.py" ask-code --request-id <id>
python3 "$HOME/.codex/skills/telegram-notify/scripts/telegram_verification.py" poll-code --request-id <id> --wait-seconds 45
python3 "$HOME/.codex/skills/telegram-notify/scripts/telegram_verification.py" finish --request-id <id>
```

Run `ask-code` only after the site actually sent the SMS. On rejection or
expiry, run `expire --request-id <id>` immediately; it notifies the user and
creates a fresh readiness button. Poll again before requesting a resend.
Bound each poll to 45 seconds or less so independent work and user updates can
continue. A `pending` result is normal and must not trigger a duplicate prompt.

The helper fails closed when a webhook or competing Bot API poller is present.
Do not disable it, restart it, consume updates through a second client, or
change credentials to force the flow. The returned code is ephemeral task data:
enter it immediately, omit it from reports, and call `finish` after verified
success or `cancel` when abandoning the request. It accepts only a numeric
reply attached to the exact force-reply prompt for the active request.

## Important Notes
- Do not spam the user. Only use this for meaningful notifications.
- Do not send routine progress updates or multiple duplicates.
- Report only success or a redacted error; never expose credential values.
- Never include a password, native-auth value, email code, or SMS code in an
  outbound message. For SMS, ask the user to reply with the code only after the
  site confirms that it was sent.
