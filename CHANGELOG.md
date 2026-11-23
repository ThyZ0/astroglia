# Changelog

Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [0.1.0] - unreleased
### Added
- SQLite store with FTS5, typed edges, version history, event log, schema versioning.
- Capability registry for Claude Code: plugins (installed + claude.ai-synced), skills, commands, agents, hooks, MCP servers (user, local, project). Incremental sync; vanished items flagged `missing`.
- Redundancy (`similar_to`) and mention (`related_to`) relations between capabilities.
- Experience memory with source-file fingerprints, stale detection, revalidation, secret refusal.
- Context Router with explainable scores, redundancy filtering, token budget.
- MCP server (10 tools), SessionStart wake-up hook, opt-in prompt routing hook.
- CLI: sync, status, doctor, route, search, show, remember, capabilities, forget, restore-version, backup, restore, install, uninstall.
