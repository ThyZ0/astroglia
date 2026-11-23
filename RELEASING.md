# Releasing Astroglia

## Name

Checked 2026-11 before the first release: `astroglia` is free on PyPI and npm, no software product uses the name,
and the 18 GitHub repositories containing it are unrelated biology projects with 0-1 stars. The previous name
(NEXUS) collided with 134k repositories, PyPI/npm packages and Sonatype Nexus.

## Every release

1. `python -m pytest` green locally; CI green on all platforms.
2. Bump the version in `pyproject.toml`, `astroglia/__init__.py`, `astroglia/mcp_server.py`.
3. Move *Unreleased* entries in `CHANGELOG.md` under the new version and date.
4. If the database schema changed: bump `SCHEMA_VERSION`, add the migration step, add a test that opens a
   database from the previous version.
5. Build and smoke-test the wheel in a fresh environment:
   ```bash
   python -m pip wheel . --no-deps -w dist
   python -m venv /tmp/nx && /tmp/nx/bin/pip install dist/*.whl
   ASTROGLIA_HOME=/tmp/nx-home /tmp/nx/bin/astroglia sync && ASTROGLIA_HOME=/tmp/nx-home /tmp/nx/bin/astroglia doctor
   ```
   Check that `astroglia ui` serves `/`, `/app.js`, `/galaxy.js`, `/style.css`.
6. Tag `vX.Y.Z`, push the tag, publish to PyPI (`python -m build && twine upload dist/*`).

## Compatibility promises

- MCP tool names and their required arguments are a public interface: additive changes only within 0.x minors.
- The database is migrated forward automatically; a database from a newer Astroglia is refused with a clear
  message, never modified.
- Hooks always fail open.
