# Contributing

1. `python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"` (Linux/macOS: `.venv/bin/pip`)
2. `python -m pytest`: every change keeps the suite green; new behaviour comes with a test.
3. Ground rules (from the project charter):
   - No fake data, no simulated activity. If something is not implemented, say so.
   - Never add a network call or telemetry to the core. Local first.
   - Every mutation must be reversible (`history`) and logged (`events`).
   - Hooks must fail open.
   - Prefer the standard library; new dependencies need a reason in the PR.
4. Schema changes: bump `SCHEMA_VERSION` in `nexus/store.py` and add a migration step; never edit an old one.
5. Commits: imperative, small, one topic. Update `CHANGELOG.md` under *Unreleased*.

Bugs: open an issue with `nexus doctor` output and steps to reproduce.
