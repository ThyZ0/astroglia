# Releasing NEXUS

## Before the first public release (open decisions)

- **GitHub repository**: create it, then replace `<you>` in README install instructions.
- **Import name**: the PyPI distribution `nexus-cognitive` is free (checked 2026-11), but the import package
  `nexus` collides with an existing PyPI project named `nexus`. Installing both in one environment would
  conflict. `pipx` isolates tools, so this only matters for library-style installs. Options: keep it (CLI
  tool, pipx-first) or rename the package to `nexus_cognitive` (breaking for hooks: re-run `nexus install`).
- **Linux/macOS**: only tested on Windows so far. The CI matrix (`.github/workflows/ci.yml`) covers
  ubuntu/windows/macos × Python 3.11–3.13 and must be green before tagging.

## Every release

1. `python -m pytest` green locally; CI green on all platforms.
2. Bump the version in `pyproject.toml`, `nexus/__init__.py`, `nexus/mcp_server.py`.
3. Move *Unreleased* entries in `CHANGELOG.md` under the new version and date.
4. If the database schema changed: bump `SCHEMA_VERSION`, add the migration step, add a test that opens a
   database from the previous version.
5. Build and smoke-test the wheel in a fresh environment:
   ```bash
   python -m pip wheel . --no-deps -w dist
   python -m venv /tmp/nx && /tmp/nx/bin/pip install dist/*.whl
   NEXUS_HOME=/tmp/nx-home /tmp/nx/bin/nexus sync && NEXUS_HOME=/tmp/nx-home /tmp/nx/bin/nexus doctor
   ```
   Check that `nexus ui` serves `/`, `/app.js`, `/galaxy.js`, `/style.css`.
6. Tag `vX.Y.Z`, push the tag, publish to PyPI (`python -m build && twine upload dist/*`).

## Compatibility promises

- MCP tool names and their required arguments are a public interface: additive changes only within 0.x minors.
- The database is migrated forward automatically; a database from a newer NEXUS is refused with a clear
  message, never modified.
- Hooks always fail open.
