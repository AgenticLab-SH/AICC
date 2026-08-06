---
name: codex-reset-credit
description: Read Codex quota, reset times, reset credits, expiry, and token totals without modifying account state.
---

# Codex usage and reset credits

Run the bundled wrapper for a sanitized, read-only account report:

```powershell
python scripts/check_reset_credits.py
```

Use `--json` when structured output is needed and `--daily-limit 0` to include every returned daily bucket.

The tool performs the required JSON-RPC handshake and calls only:

- `account/rateLimits/read`
- `account/usage/read`

Report the plan, percentage used and remaining, automatic reset in KST with remaining duration, available Full reset count, each available credit's expiry and remaining duration, and usage summary. Do not reveal account IDs, credit IDs, email addresses, auth tokens, profile URLs, or raw app-server messages.

Never call `account/rateLimitResetCredit/consume`. The bundled implementation rejects that method and does not expose arbitrary JSON-RPC input. Read `references/app-server-protocol.md` only when diagnosing handshake or response-shape drift.
