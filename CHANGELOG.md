# Changelog

Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [0.7.0] - 2026-11-23
First public release.
### Added
- Health page and MCP tool `health`: health score (freshness, verifiability, connectivity, documentation), suggested relations, overlapping memory (merge in one click), capabilities never selected, most reused resources.
- Timeline: what was learned, changed, went stale or was re-validated, day by day.
- Replay a routing in the galaxy; nebula halos over real clusters; camera turns toward the selected star; labels never overlap.
- Claude Code plugin packaging (validated with `claude plugin validate`): `/plugin install astroglia --marketplace ThyZ0/astroglia`.
- `bench/value.py`: onboarding and recall scenarios with and without Astroglia.
- README in French.
### Fixed
- The consolidation reminder now counts saves made with the CLI.
- Linux: "Show source" opens the containing folder (test adapted); CI runs every platform even when one fails.

## [0.6.0] - unreleased
Renamed from NEXUS to **Astroglia** (the old name collides with 134k GitHub repositories, PyPI/npm packages and Sonatype Nexus).
### Added
- Project briefs: deterministic summary of manifests, scripts, layout, entry points, tests, README and git hot files; stale-aware, rebuilt only when sources change; the current project's brief is part of the session manifest.
- Consolidation: a Stop hook asks once per session, after real work, to save reusable knowledge (`consolidate = false` disables it).
- `remember` reports similar existing entries (duplicates); `astroglia value` / `/api/value`: what was served (measured) vs saved (estimated).
- Galaxy: relation types by line pattern, direction arrows and labels on selection, path tracing (shift+click), family filters, 2-step expansion, first-use guide, "Show source" in the file manager.
- Evidence-based bridges between hemispheres: an indexing tool is `used_in` the projects it indexes.
- `bench/load.py` (1.5k to 20.5k entries), recall metric in `astroglia bench`, demo dataset for screenshots.
### Changed
- MCP tools have short names (`mcp__astroglia__route`, `remember`, `project`...).
- Router drops candidates below 60% of the best score: 7.0 -> 4.0 results per task, same accuracy and recall.
- Navigation grouped by intent; new logo.
### Fixed
- A deleted source file kept an entry looking valid.
### Performance
- Freshness check of 500 unchanged entries: 989 ms -> 71 ms (hash cache, schema v2, one transaction).
- API responses gzipped (galaxy payload at 20k entries: 7.8 MB -> 0.6 MB).

## [0.5.0] - unreleased
### Added
- Galaxy keyboard control (arrows rotate, +/- zoom, Esc closes the panel); "skip to content" link.
- RELEASING.md with the release checklist and open pre-release decisions.
- Robustness tests: newer database refused, unreadable config, busy port, 5000-entry routing under 0.5 s.
### Fixed
- Muted text contrast raised to WCAG AA (4.0:1 -> 4.8:1 on cards).
- `astroglia ui` on a busy port and a broken `config.toml` now print a message instead of a traceback.
- `astroglia uninstall` always backs up settings.json, even when the backups folder does not exist yet.

## [0.4.0] - unreleased
### Added
- Brain-galaxy views: Galaxy (home), Neural, Clusters, Voids. Animations driven only by the event log; reduced-motion support; palette validated for colour-vision deficiencies.
- API: `/api/graph`, `/api/voids`, `/api/events?after=` (live tailing).
### Changed
- Metadata in detail panels is folded by default.

## [0.3.0] - unreleased
### Added
- `astroglia ui`: local web interface (Dashboard, Context Monitor, Capabilities, Memory inspector with edit/merge/link/restore, Projects). Stdlib server, token + Host checks, no build step.
- Memory merge (texts, tags, fingerprints, relations; source kept in history).
### Fixed
- SQLite connection usable across threads when the library is serialized (threadsafety 3).

## [0.2.0] - unreleased
### Added
- Providers: project cards from Cortex (`cortex list/stats`), Graphify (`graph.json`, stale-graph detection vs git HEAD), project CLAUDE.md, Claude Code auto-memory files. Pointers only, no copies.
- `project` MCP tool / `astroglia project` CLI: what to reuse for a project and which files changed since.
- Wake-up manifest shows the current project, its indexes and their staleness.
- `astroglia bench`: routing benchmark vs plain BM25; labelled `bench/local-tasks.json`.
- Router: full-name match signal (`named` weight).
### Changed
- MCP `route` returns the top 5 rejections plus a count (the full list is in the event log).
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
