# Repository instructions

- This is AICC's embedded Account Manager source. Keep changes scoped to this
  component and use the AICC root for commits and pushes. Do not modify Codex,
  OCX, provider, or authentication state while developing or testing it.
- Public runtime code lives in `src/`; public tests live in `tests/`. The
  maintainer's extended cross-device implementation lives in `ops/local/`, and
  the optional self-hosted login broker lives in `ops/auth-portal/`. Architecture
  and setup details live in `docs/`. Preserve the stdlib-only runtime contract.
- Treat auth files, tokens, account stores, session databases, and resolved
  profile paths as sensitive external input. Never commit, log, fixture, or
  snapshot real credentials.
- Preserve cross-platform behavior. Platform-specific features should report or
  skip explicitly rather than changing an unrelated platform's state.
- Run `uv run --extra dev python -m pytest tests -q` for public code,
  `python3 -m unittest discover -s ops/local/tests -p 'test_*.py'` for local
  operations, and the auth-portal suite when that component changes. Do not
  claim network, deployment, or login validation unless it was actually performed.
- Before committing, review the diff, run the closest tests, scan staged content
  for secrets, and let the AICC root publication workflow push the coherent
  change without force.
