# AI Control Center repository instructions

## Scope

This private source repository is the local-first control center for AI accounts,
provider runtimes, desktop clients, browser sessions, workspaces, and related
tools. macOS is the currently live-verified host; keep other platforms portable
without claiming runtime verification that has not happened.

Treat every tracked file as potentially shareable. Repository defaults and examples must be generic.
Personal paths, account labels, emails, workspace names, credentials, and runtime
state belong only in each user's `~/.ai-control-center/config.env` or the native
tool-owned state directory.

## Safety boundaries

1. Bind the local server to `127.0.0.1` by default. Do not expose account,
   provider, browser, or process-control endpoints remotely without a separate
   reviewed authorization boundary.
2. Never commit or display tokens, refresh tokens, API keys, browser profiles,
   session databases, provider auth stores, or account files.
3. Runtime state belongs under `~/.ai-control-center`. Existing tool-owned state
   remains in its native location until a tested migration is explicitly approved.
4. Integrate vendored upstream projects through adapters. Keep upstream source
   changes minimal and separately reviewable so an agent can audit future updates.
5. AICC control-plane mutations use named allowlisted actions, one writer lock,
   precondition checks, and a documented rollback. Workspace MCP command execution
   is a separate data-plane and must remain inside its registered workspace lease
   and OS sandbox.
6. Preserve existing repositories and dirty work. Import or archive them only
   after the integrated replacement has passed equivalent tests and live smoke.

## Canonical map

- AICC orchestration and adapters: `src/`
- Embedded projects: `components/account-manager` and `components/workspace-mcp`
- Pinned upstream OCX: `vendor/opencodex` plus `vendor/opencodex.UPSTREAM.md`
- Codex and Claude guidance source: `guidance/`; generated home copies are not
  edit targets
- Host tools and guarded operations: `tools/platform/`
- Personal state: `~/.ai-control-center`; native authentication remains in the
  owning tool homes documented in `docs/state-boundaries.md`

Start agent work with `docs/agent-operations.md`. Do not create duplicate control
roots, model bridges, browser profiles, or agent homes outside the documented owners.

## Current phase

Read-only inspection remains the default surface. The only mutations are the
named actions in `src/actions.mjs`: OCX start/sync/stop and GPT account routing.
Every control-plane mutation requires a fresh preview, one-use confirmation token,
one-writer lock, pre-state match, and post-action verification. Tests must use
fake runners; never switch a real account or stop a live OCX during validation.

## Validation

On macOS, run `npm run verify:mac` before publication. For a narrow change, run
the closest component test while iterating, then the full Mac gate before push.
Root tests must never rely on recursive discovery because `components/` and
`vendor/` carry their own suites.
