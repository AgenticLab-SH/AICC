# Codex multi-account

`cm` is the canonical local manager for isolated Codex accounts. It keeps
authentication and account databases separate while sharing only declared
Codex configuration, directives, plugins, rules, and Hub-managed skills.

## Commands

```powershell
cm status
cm switch <account>
cm reset-credits [--available-only]
cm cli <account>
cm app <account> [--restart]
cm app-dry-run <account>
cm threads status
cm threads sync <account|all>
cm remote <account>|status|stop
cm import-app [name] [--dry-run]
cm refresh <account> [--once|--browser]
cm add [--once|--browser]
cm doctor
cm cleanup-temp [--yes]
cm auth-sync
cm remove
cm update
```

Run `cm help` for the installed command registry. Selectors accept the table
number, part of an email, or a recorded phone number.

## State boundaries

- `~/.codex`: current Desktop App home and configuration source.
- `~/.codex-multi/accounts`: stored account auth.
- `~/.codex-multi/homes`: account-local CLI home, auth, database, and rendered
  `config.toml`.
- `~/.codex-multi/app-profiles`: account-local Desktop App user data.

Never print auth, account IDs, credit IDs, raw usage responses, or database
contents. A failed lookup must not silently switch accounts, providers, homes,
or usage endpoints.

`cm switch` changes the current App auth only after an explicit selector.
`cm cli` and `cm app` launch isolated account state. `cm threads sync`
uses local app-server/SQLite metadata and makes no model call.

## Provider and remote boundaries

Provider/model routing remains owned by OCX or native Codex configuration.
`cm remote` connects the current App to the selected account's native Codex
app-server over one SSH transport; it does not install or run the retired Kiro
gateway. Inspect `cm remote status` before changing a live route.

## Telegram

Codex-specific Telegram helpers and their stdlib client live in `telegram/`.
Credentials stay outside Git in `~/.codex/telegram.env`. On Windows, manage the
optional polling task from this directory:

```powershell
pwsh -NoProfile -File telegram/codex_telegram_bot_task.ps1 setup
pwsh -NoProfile -File telegram/codex_telegram_bot_task.ps1 status
```

Notification failure never changes the account operation. Set
`CODEX_MULTI_NOTIFY=0` for a temporary notification-only disable.

## Optional asynchronous login portal

`../auth-portal/broker.py` can run behind an authenticated tunnel. An authorized
operator can complete an official OpenAI device login while the destination
machine is offline. The broker retains one latest credential; the Mac applies a
new job only when its local checkpoint differs. The full account ID must match
the configured cm account. With `CM_AUTH_SYNC_OPENCODEX=1`, the same event also
creates or safely replaces one explicit OCX pool slot through a temporary import
gate, verifies it, and returns OCX to its normal gate-free service.

The portal never changes the active App account. Runtime service tokens,
Cloudflare tunnel credentials, retained OAuth envelopes, checkpoints, and OCX
backups stay outside Git. Full details and recovery steps are in
`../../docs/auth-portal-ocx-sync.md`.

## Verification

```bash
python3 -m unittest discover -s ops/local/tests -p 'test_*.py'
pwsh -NoProfile -File ops/local/cm.ps1 help
pwsh -NoProfile -File ops/local/cm.ps1 doctor
```

The tests use fixtures and must not read or mutate live auth.
