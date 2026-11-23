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

## 3. Claude Code integration

- MCP does not run anything at session start, so the wake-up uses the official `SessionStart` hook with `additionalContext` (WAKE → SYNC → ORIENT → READY). Measured: ~0.6 s, ~100 tokens, on 72 capabilities.
- Hooks call `python -m nexus hook …` (not bash) so they work on Windows.
- Any exception in a hook → no output, exit 0, error logged. Claude Code is never blocked (tested).
- MCP tools are `async` so they run on the event loop thread that owns the SQLite connection.

## 4. Security

Local only. Read-only on Claude Code config except explicit `install`/`uninstall` (with backup). MCP env values are never stored. Secrets are refused in `remember`. Returned content is labelled untrusted data. All changes are versioned. No telemetry.

## Roadmap

| Version | Scope | Done when |
|---|---|---|
| **0.1** (this) | store, capability registry, experiences, router, MCP, wake-up hook, CLI | 14 tests incl. scenarios 3–6 |
| 0.2 | Providers: Cortex (`cortex pack/ask`), Graphify (`graph.json`), CC memory files; project understanding cache (scenario 1–2); routing benchmark with/without NEXUS | benchmark published |
| 0.3 | Local web UI on real data: Dashboard, Capability Explorer, Context Monitor (from `events`), Memory Inspector (edit/merge/restore) | e2e tests |
| 0.4 | Galaxy / Neural / Cluster / Void views (brain-galaxy, animations bound to `events`) | |
| 0.5 | Adaptation: learned weights, versioned and reversible; optional local embeddings; packaging + release | |
