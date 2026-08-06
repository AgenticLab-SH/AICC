# Codex app-server read-only protocol

The stdio connection uses newline-delimited JSON-RPC messages in this order:

1. Request `initialize` with `capabilities.experimentalApi=true`.
2. Wait for the matching initialize response.
3. Send the `initialized` notification.
4. Request `account/rateLimits/read` and `account/usage/read`.

`account/rateLimits/read` returns rate-limit windows, Unix-second automatic reset times, and `rateLimitResetCredits`. `account/usage/read` returns `summary` plus `dailyUsageBuckets`.

The mutating method `account/rateLimitResetCredit/consume` is outside this skill's authority. Do not add a generic method option, pass-through JSON input, credit ID output, or consume helper.

If the protocol changes, inspect generated schemas from the installed `codex app-server generate-json-schema` command or current official Codex sources before changing the allowlist. Preserve the initialize handshake and forward only sanitized fields to users.
