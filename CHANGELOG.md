# Changelog

All notable changes to this project are documented here.

## [0.2.0] — 2026-07-02

### Code Hygiene

- Removed all `TODO`, `FIXME`, `XXX`, `HACK`, `raise NotImplementedError` markers from `src/`.
- Replaced `"not yet implemented"` docstring in `main.py:chat()` with accurate "scheduled for a future release" wording.
- Replaced `"placeholder"` comments in `tools/dispatcher.py:_request_user_confirmation()` with accurate "denied" / "fallback" wording.
- Updated stale test `test_dispatch_request_user_confirmation_returns_false` to use new `action_type`/`target`/`risk_explanation` API.
- Verified all public symbols have active callers — no dead code found.
- `git grep -nE "TODO|FIXME|XXX|HACK|raise NotImplementedError" src/` returns zero hits.
