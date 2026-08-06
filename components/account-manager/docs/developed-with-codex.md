# Developed with OpenAI Codex

Codex Account Manager was developed with OpenAI Codex as an engineering
collaborator. This is not a claim that generated output was accepted without
review. The maintainer selected the product direction, defined the safety
boundaries, reviewed every change, and owns the resulting code and releases.

## How Codex contributed

Codex supported the project across the maintenance workflow:

- traced account, process, and credential flows before changes;
- implemented focused Python and cross-platform launcher changes;
- designed and expanded regression tests using synthetic credentials;
- investigated macOS, Windows, Linux/WSL, packaging, and CI failures;
- improved architecture, setup, contributing, and security documentation;
- ran local tests, package builds, isolated-install smoke checks, and GitHub
  Actions verification before release-facing changes were accepted.

## Maintainer control and verification

AI assistance does not replace project accountability. The maintainer:

- decides scope, architecture, compatibility, and release policy;
- reviews diffs before committing and uses focused, human-readable commits;
- requires the offline test suite to pass without a real account or network;
- verifies supported operating systems in GitHub Actions;
- keeps credentials, account stores, browser profiles, and session data out of
  prompts, fixtures, logs, and the repository;
- rejects claims that are not backed by code, tests, or observed runtime
  evidence.

The public validation contract is reproducible:

```bash
uv run --extra dev python -m pytest tests -q
uv build
```

The CI workflow also installs the built project and runs `cm setup --check` on
macOS, Windows, and Ubuntu with supported Python versions.

## Safety boundary

Codex is used to reason about and improve the source repository. It is not
given real authentication files or token values. Tests use temporary
directories and synthetic credentials, and release decisions remain under
maintainer review.

This workflow makes the role of Codex explicit while keeping responsibility,
security decisions, and repository control with the human maintainer.
