# Using Kiro models in the ChatGPT desktop app

Goal: open the ChatGPT (Codex) desktop app and pick a Kiro-served model such as
Claude Opus or Sonnet, instead of only the built-in OpenAI models.

Three pieces are involved, and knowing which owns what makes failures obvious:

| Piece | Role |
|-------|------|
| ChatGPT desktop app | The client you actually use |
| `ocx` (opencodex) | Local proxy that serves Kiro models and owns the Kiro login |
| `cm` (this tool) | Manages ChatGPT accounts; verifies the wiring above |

`cm` never holds Kiro credentials. It reports what the proxy resolved, so a
half-configured setup is visible rather than silently falling back.

## Setup

Order matters. `ocx login kiro` drives the running proxy's management API, so the
proxy must be started **before** the login, otherwise it fails with `Proxy is not
running`.

```bash
# 1. Install the tools
npm install -g @bitkyc08/opencodex
git clone https://github.com/AgenticLab-SH/ai-control-center.git
cd ai-control-center
npm ci
npm link
aicc setup

# 2. Start the proxy. This also injects the app routing into ~/.codex/config.toml
ocx start

# 3. Sign in to Kiro (opens a browser). Registers the kiro provider on success
ocx login kiro

# 4. Publish the Kiro models into the Codex model list
ocx sync

# 5. Optional: make Kiro the default provider
ocx provider set-default kiro

# 6. Verify the whole chain
cm setup
```

Then **fully quit and reopen the ChatGPT desktop app.** It reads its config and
model list at launch, so a running app will not pick up the new routing.

The Kiro models now appear in the app's model picker.

If a model is missing after a Kiro-side change, re-run `ocx sync` and restart the
app. Verify what the proxy currently offers with `ocx provider list`.

## What `cm setup` verifies

```
✓ opencodex        2.7.42 최신
✓ account-mode     direct
✓ 프록시            http://127.0.0.1:10100 응답함
✓ 앱 라우팅          http://127.0.0.1:10100/v1 (config.toml)
✓ kiro 자격         Kiro Desktop 로그인 (전체 모델)
```

All five must be present. When something is missing, `cm setup` prints the exact
remaining commands in dependency order, so re-running it is always safe.

The two lines people miss:

- **프록시** — the proxy must actually be running. If it is not, the app shows
  errors on every request. Start it with `ocx start`.
- **앱 라우팅** — the app's own `~/.codex/config.toml` must point at the proxy.
  Without it the app quietly uses only native OpenAI models. `ocx start` writes
  this line; if it says `네이티브`, the app is not wired up.

## Which Kiro login is in use

The `kiro 자격` line reports the credential source:

| Value | Meaning |
|-------|---------|
| `desktop` | Kiro Desktop login — full model access |
| `kiro-cli` | kiro-cli login — higher-tier models unavailable |
| `detached` | Matches no local login; the proxy refreshed its own copy. Normal. |
| `none` | Not signed in — run `ocx login kiro` |

If several Kiro logins exist on one machine, the proxy picks one by search order
and may land on a lower-entitlement `kiro-cli` credential. Pin the one you want
before logging in:

```bash
export KIRO_CREDS_FILE="$HOME/.aws/sso/cache/kiro-auth-token.json"
ocx login kiro
```

## With several ChatGPT accounts

Each account gets its own isolated home with its own `config.toml`, rendered from
`~/.codex/config.toml`. New accounts inherit the proxy routing automatically.

Accounts created *before* you ran `ocx start` keep the older config, so their
sessions would miss the Kiro models. `cm setup` re-renders them and reports how
many it updated; `cm doctor` flags any that still disagree.

Keep the proxy's Codex provider in `direct` mode (`cm setup` pins it) so the
account `cm` selected is the account billed. See [architecture.md](architecture.md).

## Troubleshooting

**Kiro models missing from the picker.** Confirm `cm setup` shows both 프록시 and
앱 라우팅, then run `ocx sync` and fully quit and reopen the app. The model list is
injected into the Codex config, so an app left running keeps the old list.

**`ocx login kiro` says the proxy is not running.** Run `ocx start` first; the
login goes through the proxy's management API.

**Worked yesterday, not today.** The proxy is probably not running after a
reboot: `ocx start`. To keep it running, use `ocx service` or `ocx codex-shim
install`, which starts it on demand when `codex` launches.

**One account sees Kiro models, another does not.** That account's config is
stale. Run `cm setup`.

**Editing the proxy's config by hand.** A running proxy rewrites its own config
from memory, so stop it first:

```bash
ocx service stop
# edit ~/.opencodex/config.json
ocx service start
```

## For an agent doing the setup

Everything below is non-interactive except the browser step. Check state before
acting; every command here is safe to re-run.

**Inspect without changing anything:**

```bash
cm setup --check          # prints each requirement and the remaining commands
cm status --json          # machine-readable account state (no secrets)
ocx provider list         # which providers exist and which is default
ocx health                # exit 0 when the proxy is healthy, 1 when not
```

**The only step needing a human:** `ocx login kiro` opens a browser for consent.
It cannot be automated. Run it, then continue.

**Order of operations**, with the reason each step depends on the previous one:

| Step | Depends on | Why |
|------|-----------|-----|
| `ocx start` | opencodex installed | Serves the API and injects app routing |
| `ocx login kiro` | proxy running | Login goes through the proxy's management API |
| `ocx sync` | Kiro login exists | Publishes the model list into the Codex config |
| restart the app | routing + model list written | The app reads both only at launch |
| `cm setup` | — | Verifies the chain; safe at any point |

**Definition of done.** `cm setup --check` shows `✓` for 프록시, 앱 라우팅 and
kiro 자격, and the app's model picker lists Kiro models after a restart. A `✗` or
`!` on any of those three means the app cannot use Kiro models yet.

**Do not** copy Kiro or ChatGPT credentials between stores. Both `ocx` and `cm`
refresh their own copies, and ChatGPT's OAuth refresh rotates the refresh token,
so two stores sharing a grant will eventually invalidate each other.
