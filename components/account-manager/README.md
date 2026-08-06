# Codex Account Manager (`aicc account`, legacy `cm`)

[![Tests](https://github.com/AgenticLab-SH/ai-control-center/actions/workflows/ci.yml/badge.svg)](https://github.com/AgenticLab-SH/ai-control-center/actions/workflows/ci.yml)
[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue.svg)](https://www.python.org/downloads/)
[![License: MIT](https://img.shields.io/badge/license-MIT-green.svg)](LICENSE)
[![Built with OpenAI Codex](https://img.shields.io/badge/built%20with-OpenAI%20Codex-111111.svg)](docs/developed-with-codex.md)

Manage multiple ChatGPT/Codex logins on one machine: switch the account the
Codex desktop app uses, run several CLI sessions under different accounts at the
same time, and see each account's remaining quota and reset times in one table.

Built by **Sanghoon Kim** ([@AgenticLab-SH](https://github.com/AgenticLab-SH)).
MIT licensed.

Developed with **OpenAI Codex as an engineering collaborator** for
implementation, cross-platform debugging, regression-test design,
documentation, and release validation. Every change remains maintainer-reviewed,
tested, and owned by the project maintainer. See
[Developed with Codex](docs/developed-with-codex.md) for the workflow and
boundaries behind that claim.

> **Project status:** Public beta. The command-line interface and JSON status
> schema may evolve before 1.0. Please report reproducible problems through
> [GitHub Issues](https://github.com/AgenticLab-SH/ai-control-center/issues).

The public Python package can still run as the standalone `cm` tool. In the
combined AICC checkout, the supported human entry points are the `aicc` TUI and
local web app, while `aicc account ...` is the stable terminal contract and
`cm ...` is a compatibility alias. The account engine does not bundle, fork or vendor
[opencodex (`ocx`)](https://www.npmjs.com/package/@bitkyc08/opencodex) or the
Codex CLI — it reads their state and reports on it when they happen to be
installed. Both remain the property of their own authors.

The recommended hybrid workflow is one normal desktop app with OCX `pool`
account selection for most work, plus `cm app <account>` only when a separate
login, database, or browser profile is useful. OCX owns pool selection; `cm`
never copies, removes, or silently switches OCX credentials. Active and archived
rollout files are shared for continuity, while every isolated app keeps its own
`state_5.sqlite` and is reconciled only while inactive.

## Repository editions

This repository keeps one project with two explicit surfaces:

- `src/` is the public, installable, cross-platform package described below.
- `ops/local/` is the maintainer's extended operational edition for account-local
  thread indexing, SSH transport, notifications, and the optional auth portal.
- `ops/auth-portal/` is the self-hosted broker and Mac importer used by the
  operational edition. All account names, URLs, Firebase client settings,
  Keychain labels, tokens, auth files, and databases are supplied outside Git.

The two implementations are colocated so they can converge safely, but are not
silently mixed: package installs keep using `src/`, while a maintainer checkout
may point its local launcher at `ops/local/codex_multi.py`. See
[`docs/operations.md`](docs/operations.md).

## What it does

- One table of every account: 5-hour and weekly quota left, reset times, plan,
  token expiry, subscription expiry.
- Switch the native/direct desktop app login (`cm switch`), restarting only that app.
- Run isolated CLI sessions per account (`cm cli`), so several accounts can be
  used to their limits concurrently.
- Launch a second desktop app instance bound to a specific account (`cm app`).
- Diagnose credential layout and account isolation (`cm doctor`).
- Report the local proxy's routing mode when `ocx` is installed (`cm stack`).

## Requirements

- Python 3.11 or newer (uses the stdlib `tomllib`).
- The Codex desktop app and/or Codex CLI, logged in at least once.
- macOS, Windows, or Linux/WSL. Some features are platform-specific and are
  skipped rather than failing where they do not apply.

No third-party Python packages are needed to run `cm`.

## Platform support

The test suite runs on macOS, Windows, and Linux for Python 3.11 and 3.13.
Commands that control the desktop app are platform-specific; unsupported
operations report that limitation instead of modifying another platform's
state.

| Capability | macOS | Windows | Linux / WSL |
|------------|:-----:|:-------:|:-----------:|
| Account and quota status | ✅ | ✅ | ✅ |
| Isolated Codex CLI homes | ✅ | ✅ | ✅ |
| Desktop app switching | ✅ | ✅ | Not applicable |
| Account-specific app launch | ✅ | ✅ | Not applicable |

Platform test coverage does not imply that every Codex desktop release has
been manually tested on every operating-system version. See
[Contributing](CONTRIBUTING.md) for the evidence expected in bug reports.

## Install

Codex Account Manager is distributed as part of AI Control Center. Clone the
combined repository and run the top-level setup:

```bash
git clone https://github.com/AgenticLab-SH/ai-control-center.git
cd ai-control-center
npm ci
npm link
aicc setup
```

The AICC account adapter and `aicc account` both run the operational edition at
`components/account-manager/ops/local/codex_multi.py`. Existing `cm` commands
continue to work by entering the same AICC path; new scripts should use
`aicc account`.

No Codex credential is read during install, and your shell profile is left
alone.

Then run setup once:

```bash
cm setup            # or: cm setup --check  (report only, changes nothing)
```

`cm setup` checks prerequisites, installs or upgrades the optional `ocx` proxy,
reports its current Codex account mode without changing OCX-owned provider state,
imports the login you already have, and verifies that the desktop app is actually
wired to the proxy. When something is
missing it prints the exact remaining commands in dependency order, so re-running
it is always safe. Anything needing a browser, an app store or an administrator
is reported rather than attempted silently.

## Using Kiro (or other proxy) models in the desktop app

To pick Claude or other Kiro-served models inside the ChatGPT desktop app:

```bash
npm install -g @bitkyc08/opencodex
ocx start           # serves the proxy and injects app routing
ocx login kiro      # needs the proxy already running
ocx sync            # publishes the models into the Codex model list
cm setup            # verifies proxy, app routing, and Kiro credential
```

Then fully quit and reopen the desktop app so it re-reads its config and model
list.

`cm` does not hold Kiro credentials — those belong to `ocx`. What `cm` adds is
verification of the whole chain, and keeping every per-account home pointed at
the proxy. Full walkthrough and troubleshooting: [docs/kiro-setup.md](docs/kiro-setup.md).

## Where your data lives

| Path | Contents |
|------|----------|
| `~/.codex` | The Codex app/CLI home. `cm` swaps `auth.json` here when switching. |
| `~/.codex-multi/accounts` | One credential file per account, owned by `cm`. |
| `~/.codex-multi/homes` | Per-account isolated `CODEX_HOME` directories with private auth/config/SQLite and shared active/archived rollouts. |
| `~/.codex-multi/config.toml` | Optional integration settings (see below). |

Override the roots with `CM_APP_CODEX_HOME` and `CM_MANAGER_DIR`.

Credentials never leave your machine. The only outbound requests `cm` makes are
to ChatGPT's own usage endpoints, to read the quota numbers it displays.

## Commands

| Command | Action |
|---------|--------|
| `cm` | Full TUI: accounts, quota, switching |
| `cm setup [--check]` | First-run setup and prerequisite check |
| `cm status [--json]` | Account and quota table, or machine-readable JSON |
| `cm switch <n>` | Switch the desktop app's account |
| `cm cli <n>` | Run the CLI under one account's isolated home |
| `cm app <n> [--restart\|--dry-run]` | Launch a separate desktop app for one account |
| `cm import-app` | Import or refresh the current `~/.codex` login |
| `cm add` / `cm refresh <n>` | Add a new account / re-authenticate one |
| `cm doctor` | Diagnose credential paths and isolation |
| `cm stack` | Report Codex CLI / opencodex versions and proxy routing |
| `cm reset-credits` | Reset-credit availability per account |
| `cm usage-proxy <n> <value>` | Per-account proxy for usage lookups |
| `cm quota-debug <n>` | Diagnose usage-lookup HTTP/network problems |
| `cm cleanup-temp [--yes]` | Inspect or clear abandoned login temp homes |
| `cm remove` | Delete a stored account |
| `cm help` | Full command list |

Accounts can be selected by table number, email substring, or account-ID prefix.
Prefer the number in interactive use and the ID prefix in scripts, since email
filenames change when an account is re-registered.

## Optional integrations

Everything in `config.example.toml` is opt-in and absent by default: the local
proxy URL, an explicit `codex` executable, and a stack-update command. Copy the
file to `~/.codex-multi/config.toml` and uncomment what you want.

`cm stack apply` deliberately has no built-in updater. A safe upgrade needs
backup and rollback steps that depend on your machine, so it runs only the
command you configure.

Inspect what resolved on your system:

```bash
python3 src/cm_integrations.py
```

## Using `cm` with opencodex

For the normal one-app workflow, keep OCX in `pool` mode and select the account
for each new task with OCX's native commands:

```bash
ocx account current openai
ocx account use openai <id>
```

The selection applies to new tasks; running tasks keep their starting account.
`cm app <account>` remains available when a separate login, SQLite database, or
browser profile is useful. In `pool` mode that separate app still uses the
OCX-selected account for each new task. Switch OCX to `direct` only when the
isolated app's own login must be the upstream account:

```bash
ocx provider account-mode direct
```

`cm stack` and `cm doctor` report the active mode but do not change it. `cm`
never copies or removes OCX pool credentials.

See [docs/architecture.md](docs/architecture.md) for how the credential paths
fit together.


## Building a dashboard on top

`cm status --json` is the supported integration surface. It emits a versioned
payload (`schema_version`) with per-account quota, reset credits and active
state, and never includes token material.

```bash
cm status --json
```

Do not patch the `ocx` dashboard to add these views. Its web UI is a compiled
bundle with content-hashed asset names shipped inside `node_modules`, so every
`ocx` upgrade replaces it and silently discards local edits. A separate consumer
of this JSON survives upgrades of both tools.

## Tests

```bash
uv run --extra dev python -m pytest tests -q
python3 -m unittest discover -s ops/local/tests -p 'test_*.py'
python3 -m unittest discover -s ops/auth-portal/tests -p 'test_*.py'
```

The test suite uses no network access and does not require a logged-in account.

## Contributing and security

Bug reports, focused fixes, documentation improvements, and cross-platform
test results are welcome. Read [CONTRIBUTING.md](CONTRIBUTING.md) before opening
a pull request. For vulnerabilities or reports that could expose credentials,
follow [SECURITY.md](SECURITY.md) and do not post secrets in a public issue.

The near-term roadmap is intentionally small:

- validate the public install path across fresh macOS, Windows, and WSL setups;
- expand regression coverage for account isolation and app lifecycle behavior;
- stabilize the versioned `cm status --json` integration contract;
- publish tagged releases after the beta interface settles.

## Safety notes

- `cm` replaces `~/.codex/auth.json` when switching accounts and keeps the
  previous credential in its own store. Deletions go to `~/.codex-multi/_trash`.
- Token material is never printed. Credential comparisons use digests.
- Automating multiple accounts may conflict with the terms of the services you
  use. Check that your usage is permitted before relying on it.
