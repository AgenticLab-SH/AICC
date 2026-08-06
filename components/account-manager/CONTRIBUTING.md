# Contributing

Thanks for helping improve Codex Account Manager. Small, reproducible changes
are easier to review and safer for a tool that handles local authentication
state.

## Before opening an issue

Search existing issues, then include:

- operating system and version;
- Python version and Codex app or CLI version;
- the exact `cm` command that failed;
- expected and actual behavior;
- a minimal reproduction that does not contain credentials.

Never paste `auth.json`, access or refresh tokens, account-store contents,
session databases, browser profiles, or complete home-directory paths. Redact
email addresses and account IDs unless they are synthetic test values.

## Development setup

The runtime is standard-library only. Development uses `uv` and `pytest`:

```bash
git clone https://github.com/AgenticLab-SH/ai-control-center.git
cd ai-control-center/components/account-manager
uv sync --extra dev
uv run --extra dev python -m pytest tests -q
```

Tests must not require a real login or make network requests. Use temporary
directories and synthetic credentials such as `fake-access-token` in fixtures.

## Pull requests

1. Keep the change focused and preserve macOS, Windows, and Linux behavior.
2. Add or update a regression test for behavior changes.
3. Run `uv run --extra dev python -m pytest tests -q`.
4. Explain which checks were static, simulated, or performed on a real device.
5. Review the diff for secrets and unrelated generated files.

Platform-specific features should report or skip unsupported operations
explicitly. Do not silently switch providers, profiles, accounts, or credential
locations to make a test pass.

## Scope

Good contributions include bug fixes, focused platform compatibility changes,
tests, documentation, and improvements to the versioned `cm status --json`
contract. Large authentication redesigns or new third-party runtime
dependencies should start with an issue describing the need, risks, and
compatibility plan.
