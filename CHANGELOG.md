# Changelog

Format: [Keep a Changelog](https://keepachangelog.com), versions: SemVer.

## [Unreleased]
### Added
- **First contact**: `astroglia` with no command shows what it is, whether it is connected to Claude Code, what it knows, and the next step (it used to print an argparse error). `astroglia install --yes` runs the first scan right away and reports what it found, so `astroglia ui` is not empty before the next session.
- Human-readable output for `install`, `doctor`, `sync`, `status`, `value` and `route` (colours only on a terminal, `NO_COLOR` respected); `--json` keeps the machine form for scripts.
- **Time travel in the Atlas**: a slider shows the brain as it was on a given day (entries' real creation dates), and "▶ Growth" replays how the knowledge grew. With "reduce motion" enabled in the OS (it is on the development machine), the replay runs in ten discrete stages instead of a continuous animation.
### Fixed
- The Atlas toolbar no longer wraps onto two lines.

## [0.12.0] - 2026-11-24
### Performance
- Atlas at 20,000 entries (headless Chrome, software rendering), measured: placement 4,800 ms -> 33 ms (pre-computed region raster, spatial hash, sunflower spiral for constellations over 120 stars); panning 44 -> ~80 frames/s by caching plate, constellation lines and plain stars in an off-screen layer that panning only moves; star size adapts to density and only the largest constellations are named when zoomed out. Two intermediate attempts (one batched path of 20k arcs: 24 fps; pre-drawn sprites: 17 fps) were measured slower and dropped.
### Added
- **Recurring errors**: every failed command's error signature (distinctive tokens, no paths or numbers) is logged. When the same error comes back in another session and no fix was saved, Claude is told how many times and where it happened before, and asked to save the fix once solved; a saved fix still takes priority (déjà vu). Health lists recurring errors with or without a fix; `astroglia value` counts `recurring_flagged`. Measured on this install's 5 past transcripts: 19 distinct errors, none repeated across sessions yet, so its value is not demonstrated here; it costs one indexed insert per failure and stays silent until an error recurs.
### Changed
- The whole interface follows the Atlas identity instead of a generic dashboard look: serif italic titles and serif numerals, hairline borders instead of shaded cards, one gold accent for actions and selection (contrast 10-11.7:1), navigation sections set in italic. Chart marks keep the validated blue.
- **The galaxy is replaced by the Atlas**: a brain in lateral section drawn as an anatomical plate crossed with a star chart (graticule, ink outlines, serif region titles, no glow). Regions carry meaning from their real counterparts: frontal lobe = what Claude can do (skills, commands, agents), temporal lobe = what it learned (memory), parietal lobe = projects, occipital lobe = senses (MCP servers), cerebellum = reflexes (hooks), brainstem = Astroglia's core, where pulses start. 2D pan and zoom at the cursor; plugins and projects form constellations through their stored relations; selected relations become gold arcs with direction and type; the view slides so the selected star is never under the side panel; region titles keep a fixed size and fade when zoomed in; labels never overlap. Redraws only when something changes.

## [0.11.0] - 2026-11-24
### Added
- **What changed** for a stale entry: the git commits and patches that touched its source files since it was verified, plus uncommitted changes (capped). In the node panel ("What changed since it was recorded") and as the MCP tool `changes(id)`, so Claude can revalidate or update in seconds instead of re-analysing.
### Verified
- First real-session firings: the anchored-memory hook warned, during an actual Edit in Claude Code, that a remembered experience depends on the edited file; déjà vu fired on a real failed command (`SyntaxError: unterminated string literal`) and served the remembered fix with the matched terms. No hook errors.
- Projects page: where the last session stopped (handoff note) and the full project brief Claude receives.
- Memory page: "+ New entry" form to write a decision or experience yourself, tied to its files (`POST /api/remember`, secrets refused, similar entries reported).
- Quick search (Ctrl+K or /) to jump to any skill, tool, memory or project from any page.
- The galaxy animates memory served at the file, déjà-vu hits and briefs served (real events, named in the ticker).
### Fixed
- Components with their own `display` rule ignored the `hidden` attribute (the galaxy legend could not be closed). The legend is now foldable and stays folded.
- **Handoff note**: at each turn end, Astroglia records where the session stands in its project (last request typed by the user, files of that project edited, last real error; permission refusals and files outside the project are left out). The next session started in that project shows it in the manifest (skipped when resuming the same session, kept 14 days). Deterministic, local; 176 ms on a 31 MB transcript.
- Dashboard and Context Monitor show déjà-vu hits; `astroglia value` counts them (`dejavu_served`).

## [0.10.0] - 2026-11-24
### Added
- **Déjà vu**: when a shell command fails (PostToolUseFailure on Bash/PowerShell), Astroglia checks whether the same error was already solved and remembered, and tells Claude with the matched terms. Only the lines that state the error are analysed, and it speaks only on a strong match. Replayed on 35 distinct real errors from this install's transcripts: 0 false matches (4 of 10 with the first version, which read the whole output). The consolidation reminder now quotes the errors met in the session, so the saved fix carries the text déjà vu recognises.
- Anchored memory now also reacts when Claude reads or edits code through Cortex (`cortex_read`, `cortex_card`, `cortex_outline`, `cortex_context`, `cortex_edit`; Cortex ids and project-relative paths resolved; dry runs ignored). Cortex recommends its tools before reading files, so most code reads used to bypass anchored memory. The hook only runs after Cortex has answered and only adds context.
### Fixed
- `astroglia probe` could start a second copy of a server already used by Claude Code. Spectra, at start-up, closes Chrome instances it considers orphaned, so a probe could disturb a live browser session. Probe now skips any server whose program is running.
- Stale warnings delivered by anchored memory were not counted in `astroglia value` (dashboard showed 2 stale entries, 0 warnings).
### Performance
- Session start: every sync committed each of ~170 unchanged rows separately. `Store.batch()` groups a sync into one transaction: Astroglia's part of start-up 146-1064 ms -> 119-142 ms on a real install (whole hook incl. Python start-up: 330-880 ms -> ~300 ms).
### Added
- `astroglia doctor` flags local MCP servers not yet probed.
- README screenshots for Health and Timeline, retaken on 0.9.

## [0.9.0] - 2026-11-24
### Added
- `bench/holdout-tasks.json`: 15 routing tasks written separately to check generalisation. It revealed hit@1 0.40 on unseen phrasing.
- Everyday-word synonyms (todo -> task, workbook -> spreadsheet, mail -> email...) and descriptions for well-known services (Gmail, Slack, Linear, Jira, Notion, GitHub...), whose MCP configuration holds only a command line. Holdout hit@1 0.40 -> 0.80, hit@3 0.53 -> 0.93; local 0.82 -> 0.86.
- `bench/blind-tasks.json`, run once: hit@1 0.67, hit@3 0.67, recall 0.70 (BM25: 0.60). Not to be tuned against.
- `astroglia probe`: asks local (stdio) MCP servers for their tool list (MCP tools/list), so routing knows what a server does instead of seeing only its command line. Explicit only (it starts configured programs); remote servers are never contacted; re-probed only when the command line changes; failures recorded, server logs go to `probe-servers.log`. Real install: Cortex 23 tools, Spectra 38, 1.5 s. Blind check hit@1 0.67 -> 0.80, recall 0.70 -> 0.77.
- `bench/blind2-tasks.json`, run once: hit@1 0.73, hit@3 0.87, recall 0.79 (BM25 0.67).
- Context Monitor and Dashboard show memory served at the file.
### Changed
- The consolidation reminder lists full paths of edited files.
- Feedback is contextual: "not useful" counts for similar tasks only (weighted by term overlap with the task it was given for; the task is taken from the routing that returned the resource). Before, one negative rating penalised a skill for every task: a rating given while integrating Cortex pushed `study-quiz` below `study-cards` for "quiz me on chapter 3". Local hit@1 back to 0.86.

## [0.8.0] - 2026-11-24
### Added
- **Anchored memory**: a PostToolUse hook on Read/Edit/Write/MultiEdit/NotebookEdit. After Claude reads a file, it receives what Astroglia remembers about that file (once per file per session), flagged STALE when the file changed since recorded. After an edit, it is told which decisions and experiences depend on that file and how to revalidate or update them (once per entry per session). Only entries written by Claude or the user are served. Measured: ~100 ms per call end to end, of which 64 ms is Python start-up; lookup 24 ms on 20,500 entries.
- `astroglia value` counts anchored entries served.
### Verified
- CI green on Linux, macOS and Windows with Python 3.11, 3.12 and 3.13.

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
