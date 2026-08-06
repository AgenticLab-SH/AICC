---
name: codex-multi-account
description: Inspect account identity, switch, reconcile threads, or remotely connect isolated Codex accounts while preserving authentication and account-local runtime state. Use for multi-account lifecycle and transport work; use codex-reset-credit for a read-only quota, reset-time, reset-credit, or token-usage report from the active account.
---

# Codex multi-account

Use the active `${CODEX_HOME:-~/.codex}` as the App-home source of truth and
AICC `components/account-manager/ops/local` as the canonical `cm`
implementation. Never hand-edit generated homes under `~/.codex-multi/homes`.

## Boundaries

- Preserve authentication, provider, browser-profile, and user session state.
- App auth is `${CODEX_HOME:-~/.codex}/auth.json`; stored account auth is under
  `~/.codex-multi/accounts`. Never print tokens.
- `config.toml` is rendered per account from the App home; it is intentionally
  a regular file. `state_5.sqlite` is account-local and must not have multiple
  app-server writers.
- Change AICC-managed skills or directives in AICC guidance and deploy them.
  Change `cm` in the embedded account-manager component, then run its public, local, and relevant
  auth-portal tests.
- `cm` does not own OCX providers. Read OCX through `aicc account ocx ...` and
  change its selected routing account only through AICC's guarded
  `ocx.account.use` action.

## Commands

- `cm status`: list exact configured account identity and high-level status when
  choosing a multi-account target. Do not use it as a substitute for the
  detailed read-only quota and reset-credit report in `codex-reset-credit`.
- `cm cli <account>` / `cm app <account>`: isolated CLI or App.
- `cm switch <account>`: disruptive active-App account switch.
- `cm threads status|sync <account|all>`: reconcile inactive local thread
  indexes without model calls.
- `cm remote <account>`: connect the current App to one account-local
  app-server over loopback SSH.
- `cm remote status|stop|restart <account>`: inspect or control only the owned
  transport.
- `aicc account ocx list --json`: list the OCX pool with safe identities,
  plans, active selection, paused state, and reauthentication state.
- `aicc account ocx current --json`: read the account selected for new OCX
  tasks. Running tasks keep the account they started with.
- `aicc account ocx refresh`: refresh and report every OCX pool account's
  current limit usage and reset time. Use this for pool-wide quota questions;
  `cm status` and `codex-reset-credit` describe cm or the active Codex account,
  not the whole OCX pool.
- For a user-requested OCX selection change, resolve one exact healthy pool id
  from `aicc account ocx list --json`, run
  `aicc action preview ocx.account.use --selector <id> --json`, then execute the
  returned one-use confirmation with
  `aicc action execute --confirmation <token> --json`. Verify with both
  `aicc account ocx current --json` and `aicc account ocx refresh`. Never select
  a paused or `needsReauth` account, and never copy or edit OCX credentials.

When no exact account was supplied, show `cm status` and ask the user to choose.
Resolve connection values with `cm remote status`; never guess a port, user, or
identity path. Do not edit App databases directly, share one live SQLite DB,
terminate unrelated SSH or Apps, or replace `auth.json` for a remote connection.
If the target account already has a live writer, stop and ask the user to close
that session before retrying.

For explicit thread-index repair, use `--force` only when existing title or
preview recency must be rebuilt. Verify database integrity and recovery-copy
creation from the command result. Run the `ops/local/tests` suite after
implementation changes; do not infer correct propagation from launchers or
symlinks alone.
