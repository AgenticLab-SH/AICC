# Codex browser work modes

## Purpose

Keep the user's interactive browser session separate from durable automation.
The discovery surface may contain personal state; the delivered automation
must be reproducible without Codex.

## Mode 0: Default interactive browser work

Use the background in-app Browser for ordinary UI and Web GPT when its verified
account/workspace fits. Account order and workspace names come only from the
private coordination file; preserve unrelated sessions without reserving a Chrome port.
Use `Manage-CdpChromeSlotLease.ps1 -Action
Acquire` for profile-bound browser QA and provider-console setup. It selects
the least-loaded registered 9222/9223 slot, starts it without foreground activation, verifies
identity, and creates a new target. Each port may host several target leases.
Running listeners and pre-existing user tabs do not become agent-owned or block
the lease. Existing tabs never become agent-owned merely because their URL
matches the task.

For Web GPT fallback, pass the account alias and workspace returned by private
coordination. Account routing selects a login identity; both
9222 and 9223 remain agent-owned shared ports. Agent-owned 9224 is a separate
on-demand isolated QA browser and does not join this authenticated lease pool.

Operate only on the returned `target_id`, set `BROWSER_AGENT_HOME` to its
returned task-local control directory, heartbeat before each action batch, and
release immediately after each browser-action interval. The target is created in the background; do not run
`tab-switch`, `select-tab`, or `Target.activateTarget`. Browser,
Chrome-extension, and Computer Use surfaces
count as CDP-backed only when they can bind that endpoint, profile, and target;
foreground-only surfaces must not run concurrently on the shared authenticated
slots. Otherwise use endpoint-capable control or report the limitation. When
configured target capacity is full, wait boundedly or report busy. Do not silently add overflow profiles or
fall back to Whale or normal Chrome.

## Mode 1: Continue the user's existing Whale session

Use this mode only when the user explicitly asks to continue a page, tab, login,
extension, or Whale browser state they were already using.

1. Assert that CDP `9335` belongs to the dedicated Whale app and configured
   `Profile 1`.
2. Use the existing Whale tab named by the user; never choose by tab position.
3. Do not read profile databases, cookies, password stores, or local storage as
   a substitute for verified browser control.
4. Do not switch to Chrome, another Whale profile, or another port when the
   configured Whale session is unavailable.
5. Never close a tab that existed before the current run.

6. Preserve the user's download behavior. Ordinary tab actions must use the
   raw CDP/browser-client path, or Playwright 1.60+ `connectOverCDP` with
   `noDefaults: true`. Do not attach a legacy Playwright runtime that installs
   `Browser.setDownloadBehavior` on the default context. If a legacy attach is
   unavoidable, restore browser-level behavior to `default` in cleanup before
   releasing the target; a failed restore is a hard failure.

Prerequisites:

- The dedicated CDP Whale app is running on `127.0.0.1:9335`.
- Its process arguments match the configured user-data root and `Profile 1`.
- The requested tab is already present, or the user explicitly asks to open it.

## Mode 2: Build repeatable automation

Use this mode when the user wants a repeated workflow that should run later
without Codex.

### Discovery

1. Prefer an official API or connector when it is authoritative and sufficient.
2. When the workflow needs the user's existing cache, login, or web settings,
   use the matching registered CDP Chrome `9222` or `9223` profile. Use Whale
   only when the workflow explicitly needs the user's existing Whale tab state.
3. Record stable role/name locators, navigation states, output schema, and
   failure evidence. Do not make the discovery browser the production runtime.

### Runtime contract

Deliver:

- Playwright code with stable semantic locators;
- configuration outside source code;
- checkpoint/resume and bounded retry behavior;
- structured stdout and manifest/output files;
- one-item or dry-run smoke mode;
- tests for parsing, state transitions, and critical selectors;
- `run.sh` and `run.ps1`, or equivalent Mac/Windows entrypoints;
- setup documentation and an example environment file;
- no password, cookie, token, or machine-specific absolute path in source.

For public/stateless work, the runtime owns an isolated Playwright browser
context. For this user's authenticated/profile-bound work, use the matching
registered CDP Chrome `9222` or `9223` profile so its existing cache, login, and
web settings remain available. The delivered entrypoint must start the
registered slot when needed, verify its process/profile/port identity, lease
only owned tabs, and fail clearly if the expected profile is unavailable.
Never point the runtime at the user's normal Google Chrome profile.

An existing shared CDP endpoint is the selected default for profile-bound
automation, not for portable/stateless automation. Use it only when the
workflow intentionally depends on the registered profile, AICC routing,
CDP Whale, or coordinated Web AI tab leases.

For CDP Whale continuation, the runtime contract also includes preserving the
human download path: no legacy Playwright default-context overrides, task-local
artifact directories for agent downloads, and explicit `saveAs` when a file
must be retained.

### Completion gate

The work is complete only when a fresh shell can run the documented entrypoint,
the one-item smoke succeeds, representative output matches browser evidence,
and the next run can resume without an agent-owned tab.

## Browser routing

| Need | Surface |
|---|---|
| Ordinary web UI and verified Web GPT | Background in-app Browser |
| Stateless isolated browser QA | Agent Chrome 9224, start and stop on demand |
| Profile-bound console setup or authenticated QA | Shared agent CDP Chrome 9222/9223 with a short target lease |
| Explicitly continue the user's existing Whale tab/login/state | Verified CDP Whale 9335, configured Profile 1 |
| Profile-bound automation discovery and testing | Matching verified CDP Chrome 9222/9223 |
| Explicit normal-Chrome handoff | Normal Google Chrome through Codex extension |
| Standalone public automation | Playwright-owned isolated context |
| Standalone authenticated/profile-bound automation | Registered CDP Chrome slot with verified launcher and lease |
| AICC account-routed Chrome batch | Registered CDP Chrome 9222/9223 |
| Explicit Whale automation | Explicit CDP Whale 9335 |

## Extension placement

- Keep the ChatGPT Chrome Extension installed and enabled in exactly one
  authenticated Chrome profile selected by the private coordination file.
  Remove it from normal Chrome and every other CDP or QA profile so an
  extension-backed request cannot bind the wrong account silently.
- The selected profile may be a registered CDP Chrome slot only when the user
  explicitly chooses that persistent account route. Verify the extension
  transport against that exact profile after installation; do not fall back to
  another Chrome profile when it is unavailable.
- Whale continuation uses CDP 9335 and does not require the ChatGPT Chrome
  Extension.
- Never remove, disable, relocate, or alter Bonjourr while optimizing browser
  extensions.
