# Maintainer operations

The installable public package remains in `src/`. The maintainer's current
operational command lives in `ops/local/` so SSH transport, thread reconciliation,
Telegram notification, and the optional auth portal can evolve in the same
project without exposing machine state or changing the public package silently.

## State boundary

- `~/.codex` remains the Codex App home and configuration source.
- `~/.codex-multi` contains account auth, account-local homes, databases, and
  runtime transport state. Never commit it or share one live database writer.
- `~/.ai-control-center/account-manager/auth-portal.env` contains non-secret local
  routing such as the target account label, portal URL, and Keychain service.
- Auth portal bearer tokens remain in macOS Keychain or the protected server
  environment. Firebase client config is public but deployment-specific and is
  still supplied through the protected server environment.

Start from `ops/auth-portal/local.env.example` and keep the real file mode 0600.
Server settings use `ops/auth-portal/broker.env.example` as a field reference;
the real `/etc/cm-auth-broker.env` must be mode 0600.

## Local launcher

A checkout-based maintainer launcher may execute:

```bash
python3 /path/to/ai-control-center/components/account-manager/ops/local/codex_multi.py "$@"
```

Package users continue to receive the `src/` command. Test both surfaces before
moving shared behavior from the operational edition into the public core.

## Verification

```bash
uv run --extra dev python -m pytest tests -q
python3 -m unittest discover -s ops/local/tests -p 'test_*.py'
python3 -m unittest discover -s ops/auth-portal/tests -p 'test_*.py'
python3 ops/local/codex_multi.py help
```

`help`, `threads status`, and `remote status` are safe read-only smoke checks.
Do not use switch, login, sync, restart, or deployment as a smoke test.
