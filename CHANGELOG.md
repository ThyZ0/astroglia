# Changelog

Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [0.4.0] - unreleased
### Added
- Brain-galaxy views: Galaxy (home), Neural, Clusters, Voids. Animations driven only by the event log; reduced-motion support; palette validated for colour-vision deficiencies.
- API: `/api/graph`, `/api/voids`, `/api/events?after=` (live tailing).
### Changed
- Metadata in detail panels is folded by default.

## [0.3.0] - unreleased
### Added
- `nexus ui`: local web interface (Dashboard, Context Monitor, Capabilities, Memory inspector with edit/merge/link/restore, Projects). Stdlib server, token + Host checks, no build step.
- Memory merge (texts, tags, fingerprints, relations; source kept in history).
### Fixed
- SQLite connection usable across threads when the library is serialized (threadsafety 3).

## [0.2.0] - unreleased
### Added
- Providers: project cards from Cortex (`cortex list/stats`), Graphify (`graph.json`, stale-graph detection vs git HEAD), project CLAUDE.md, Claude Code auto-memory files. Pointers only, no copies.
- `nexus_project` MCP tool / `nexus project` CLI: what to reuse for a project and which files changed since.
- Wake-up manifest shows the current project, its indexes and their staleness.
- `nexus bench`: routing benchmark vs plain BM25; labelled `bench/local-tasks.json`.
- Router: full-name match signal (`named` weight).
### Changed
- MCP `nexus_route` returns the top 5 rejections plus a count (the full list is in the event log).
- `Store.reconcile` shared by all incremental syncs.

## [0.1.0] - unreleased
### Added
- SQLite store with FTS5, typed edges, version history, event log, schema versioning.
- Capability registry for Claude Code: plugins (installed + claude.ai-synced), skills, commands, agents, hooks, MCP servers (user, local, project). Incremental sync; vanished items flagged `missing`.
- Redundancy (`similar_to`) and mention (`related_to`) relations between capabilities.
- Experience memory with source-file fingerprints, stale detection, revalidation, secret refusal.
- Context Router with explainable scores, redundancy filtering, token budget.
- MCP server (10 tools), SessionStart wake-up hook, opt-in prompt routing hook.
- CLI: sync, status, doctor, route, search, show, remember, capabilities, forget, restore-version, backup, restore, install, uninstall.
