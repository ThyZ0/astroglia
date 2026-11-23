# NEXUS architecture

## 1. Positioning (audit, 2026-11)

Audited on a real install (Windows 11, Claude Code, Cortex, Graphify 0.9.115):

| | Cortex | Graphify | Claude Code native memory | NEXUS |
|---|---|---|---|---|
| Domain | Code: symbols, calls, tests | Any files → knowledge graph | Free-form Markdown facts | Capabilities + experiences |
| Budgeted context | yes (`pack`, `ask`) | `query --budget` | no (all loaded) | yes (`route`) |
| Incremental | blake3 hashes | `update` / `watch` | n/a | file hashes per entry, per-capability upsert |
| Capability index | no | no | no | **yes** |
| Experiences with validity | no | no | no | **yes (stale detection)** |
| Explains picks/rejections | partial | no | no | **yes** |

Decision: **NEXUS does not index code.** Code questions go to Cortex/Graphify, which already do it well. Planned v0.2 *providers* will query them and merge results into the router output.

## 2. Components

```
Claude Code ─ hooks: SessionStart (wake-up), UserPromptSubmit (opt-in routing)
           └─ MCP stdio: nexus_route / search / get / remember / feedback / ...
                         │
                  nexus core (Python, stdlib + mcp + pyyaml)
   capabilities.py   discover + incremental sync, redundancy & mention edges
   experiences.py    remember / verify / revalidate, secret refusal, file fingerprints
   router.py         FTS5 candidates → weighted score → greedy selection with reasons
   store.py          SQLite: nodes, edges, FTS5, history (versions), events, kv
   hooks.py          fail-open hook entry points
   cli.py            user commands, install/uninstall, backup/restore
```

### Data model

- `nodes(id, kind, title, summary, body, ref, source, project, tags, confidence, importance, status, created, updated, verified, fingerprint, meta, uses, successes)`
  - kinds: `plugin skill command agent mcp_server hook experience decision knowledge project`
  - status: `active stale missing disabled archived`
  - `body` only for content NEXUS owns (experiences). External things are referenced by `ref` (path), never copied.
- `edges(src, dst, type, source, confidence, created, verified)`; types: `belongs_to depends_on related_to complements replaces similar_to used_in derived_from referenced_by incompatible_with`. `source` says who asserted it (`scan:claude-code`, `auto:lexical`, `auto:mention`, `agent`, `user`).
- `history`: full snapshot before every change or delete → `restore-version`.
- `events`: append-only log (sync, route, remember, feedback, wake). It will feed the Context Monitor and the UI animations: the UI may only animate what is in this log.
- Schema version in `PRAGMA user_version`; migrations in `Store._migrate`.

### Router scoring

```
relevance  = 0.5 · (bm25 / best_bm25) + 0.5 · (share of task terms found in the entry)
freshness  = 0.5 ^ (days since verified / half_life_days)
success    = (successes + 1) / (uses + 2)          # Laplace-smoothed feedback
project    = 1 if entry belongs to the given project
score      = Σ weight_k · component_k              # weights in ~/.nexus/config.toml
```

Selection is greedy by score, rejecting: below `min_score`, redundant (`similar_to` ≥ `redundancy_threshold` with an already selected entry), `max_per_kind` reached, or over the token budget. Entries with file fingerprints are re-hashed at selection; changed sources → `STALE` warning and score × 0.6. Plugins and hooks are excluded by default (plugins duplicate their skills; hooks run on their own).

Why a relevance blend: relative BM25 alone always gives the best hit 1.0, even for an unrelated task. Term coverage anchors it, so an unrelated task returns nothing.

### Redundancy and relations

- `similar_to` (auto:lexical): Jaccard over description terms ≥ 0.35. On a real 47-skill install, only one pair qualifies (two browser skills). Lexical similarity is a weak signal; embeddings are the planned upgrade, gated by a benchmark.
- `related_to` (auto:mention): a description that names another capability (`"not for flashcards (study-cards)"`). This is high precision and free.

### Providers (v0.2)

`providers.py` points to external systems instead of copying them:

| Source | What NEXUS stores | How |
|---|---|---|
| Cortex | `project:<name>` card: root, files/symbols, languages, "query with cortex_pack/ask" | `cortex list` + `cortex stats` (read-only, ~60 ms each) |
| Graphify | graph path, node/edge counts, community names (as tags, so tasks find the project), `built_at_commit` vs git HEAD → **stale** flag + `graphify update` hint | parse `graphify-out/graph.json`, cached by mtime |
| Project CLAUDE.md | `knowledge` pointer (ref + 300-char excerpt) | file read |
| Claude Code auto-memory | `knowledge` pointer per memory file (name, description, type) | frontmatter |

Project roots: config `project_roots`, Cortex roots, and Claude Code's known projects plus their direct children that contain a project marker (`.git`, `pyproject.toml`, `package.json`, `CLAUDE.md`, `graphify-out`…). The home directory and desktop scratch workspaces are skipped.

`Store.reconcile(nodes, source)` is the single incremental-sync primitive: upsert what a source reports, flag what it no longer reports as `missing`.

### Project understanding (scenarios 1–2)

There is no separate cache format: understanding is stored as ordinary entries (`nexus_remember`, one per module/aspect, each with the files it was derived from). `project_card` re-hashes those files and splits entries into valid and stale, with the exact changed files. A change to `billing.py` invalidates "Billing" and "Architecture" but not "Routes". The agent re-checks only those parts.

### Measured (bench/local-tasks.json, 22 tasks, one real install)

| Variant | hit@1 |
|---|---|
| plain BM25 | 0.82 |
| router v0.1 (BM25 + coverage) | 0.82 |
| + IDF-weighted coverage | 0.73 (dropped) |
| + name fragments match | 0.73 (dropped: "test", "claude" too generic) |
| + full-name match (kept) | 0.86 |
| same, after projects added to the corpus | 0.82 (one borderline task flips) |

Honest reading: on capability routing, NEXUS's scoring is at best slightly ahead of BM25. Its value is elsewhere: redundancy filtering, explanations, staleness, project cards, experiences. Remaining misses are synonyms. That is the trigger for optional local embeddings.

## 3. Claude Code integration

- MCP does not run anything at session start, so the wake-up uses the official `SessionStart` hook with `additionalContext` (WAKE → SYNC → ORIENT → READY). Measured: ~0.6 s, ~100 tokens, on 72 capabilities.
- Hooks call `python -m nexus hook …` (not bash) so they work on Windows.
- Any exception in a hook → no output, exit 0, error logged. Claude Code is never blocked (tested).
- MCP tools are `async` so they run on the event loop thread that owns the SQLite connection.

### Web UI (v0.3)

`web.py` is a stdlib `HTTPServer` (single-threaded, local single user) over the same `Store`. The front end (`nexus/ui/`) is plain HTML/CSS/JS, shipped as package data, so there is no Node and no build step. That revises the earlier Vite/Three.js plan for the 2D views; the 3D galaxy (v0.4) will vendor one ES module. Access control: bind 127.0.0.1; per-run token in the URL fragment (never sent in requests except as the `X-Nexus-Token` header); `Host` must be localhost (DNS-rebinding guard); CSP `default-src 'self'`. Stored text is rendered with `textContent` only. Mutations reuse Store methods, so they are versioned and logged like CLI/MCP changes. Merge folds one entry into another (texts, tags, file fingerprints, relations) and deletes the source into history.

### Brain-galaxy (v0.4)

`ui/galaxy.js` renders the store as a brain: two hemisphere ellipsoids (left: capabilities, right: memory and projects). Clusters (a plugin, or a project) are placed on the cortex from a hash of their key, and members around their cluster from a hash of their id, so the map is stable between visits and needs no physics simulation. Rendering is a hand-written perspective projection on Canvas 2D with pre-rendered glow sprites. Three.js was judged unnecessary for a few thousand points and would have been the project's first vendored front-end dependency.

Honesty rules, enforced in code:
- no decorative stars: the hemispheres are drawn as faint outlines, never filled with fake points;
- animations come only from tailing `/api/events?after=<id>`: `route` gives a core ring, pulses to each selected id and a brief highlight of the clusters used; `memory.*`/`sync.*` reload the graph and new ids "are born"; `feedback` flares the rated entries; `wake` rings the core. A ticker names the event behind each animation;
- `prefers-reduced-motion`: no rotation or travel, static redraws only.

Colour: 3 categorical families (capability / memory / project), validated with the dataviz palette validator in `--pairs all` mode on the page background. Six per-kind colours failed it (deutan ΔE 1.6, normal-vision ΔE 9.8), so kind is encoded by shape (ring = plugin, diamond = MCP server) and hemisphere, not colour.

Voids (`/api/voids`) are rule-based and every group states its rule in the UI.

## 4. Security

Local only. Read-only on Claude Code config except explicit `install`/`uninstall` (with backup). MCP env values are never stored. Secrets are refused in `remember`. Returned content is labelled untrusted data. All changes are versioned. No telemetry.

## Roadmap

| Version | Scope | Done when |
|---|---|---|
| **0.1** (this) | store, capability registry, experiences, router, MCP, wake-up hook, CLI | 14 tests incl. scenarios 3–6 |
| **0.2** (this) | Providers: Cortex, Graphify, CLAUDE.md, CC memory; project cards (scenarios 1–2); routing benchmark vs BM25 | 21 tests, bench in README |
| **0.3** (this) | Local web UI on real data (`nexus ui`): Dashboard, Context Monitor, Capabilities, Memory (edit/merge/link/restore), Projects. Stdlib HTTP server, no build step | 26 tests + scripted browser walkthrough |
| **0.4** (this) | Galaxy / Neural / Cluster / Void views. Canvas 2D projection, no 3D library; animations from `events` only | 27 tests + scripted walkthrough with a real routing event |
| **0.5** (this) | Stabilisation: clean-wheel install test, failure modes (bad config, busy port, newer DB), 5000-entry performance test, WCAG contrast fix, galaxy keyboard control, release procedure | 32 tests |
| next | Learned ranking weights (versioned, reversible); optional local embeddings if the bench shows synonym misses matter | bench |
