# NEXUS

**Your agent already has dozens of skills, plugins, MCP servers and past solutions. NEXUS tells it which ones matter for the task at hand, and why.**

NEXUS is a local cognitive layer for Claude Code (and, later, other agents):

- **Capability registry.** Discovers every skill, plugin, command, agent, hook and MCP server installed, links them, and detects overlaps.
- **Experience memory.** Stores what was learned (fixes, decisions, project knowledge) *together with the hashes of the files it depends on*. When those files change, the entry is flagged **stale** instead of being served as still true.
- **Context Router.** For a task, returns a short ranked list of pointers within a token budget, with a score breakdown for every pick and a reason for every rejection (redundant, over budget, low relevance…). Deterministic: no LLM call, no cloud.
- **Cognitive wake-up.** A `SessionStart` hook gives Claude a ~100-token manifest of what is available and what changed since the last session.

It complements, not replaces, code-level tools such as Cortex (AstroQuest) and [Graphify](https://graphify.com): those index *code*. NEXUS indexes *what the agent can do and what it already learned*.

> Status: **v0.1, core only.** The galaxy-brain UI is on the roadmap ([docs/ARCHITECTURE.md](docs/ARCHITECTURE.md#roadmap)). Nothing in this README describes a feature that is not implemented.

## Example

```console
$ nexus route "relire mon code et trouver les bugs avant le merge" --budget 500
selected  skill:ponytail@ponytail:ponytail-audit             0.717
selected  skill:superpowers@synced:requesting-code-review    0.548
selected  skill:superpowers@synced:receiving-code-review     0.518
rejected  skill:ponytail@ponytail:ponytail-review            max_per_kind 3 reached for skill
...
$ nexus route "open a website in the browser and fill a form"
selected  skill:user:chrome-browser                          0.835
rejected  skill:user:built-in-browser    redundant with skill:user:chrome-browser (similarity 0.38, lower score)
```

(Output abridged; the real output is JSON with a `why` breakdown per entry.)

## Install

Requires Python ≥ 3.11 and Claude Code.

```bash
pipx install git+https://github.com/<you>/nexus   # or: pip install -e . from a clone
nexus sync                 # first scan (read-only on ~/.claude)
nexus install              # dry run: shows exactly what will change
nexus install --yes        # adds the SessionStart hook (settings.json is backed up) and registers the MCP server
nexus doctor               # checks everything
```

Opt-in: `nexus install --yes --prompt-hook` also routes every prompt and injects high-confidence pointers. It costs context on every message, so it is off by default.

Uninstall: `nexus uninstall` (removes the hook and the MCP entry) and `nexus uninstall --purge --yes` (also deletes `~/.nexus`).

## Use from Claude (MCP tools)

| Tool | Purpose |
|---|---|
| `nexus_route(task, project?, budget?)` | Pick what to use for a task, with reasons |
| `nexus_search(query, kind?)` | Plain ranked search |
| `nexus_get(id)` | Full entry, relations, validity check |
| `nexus_remember(title, summary, body?, kind?, project?, files?)` | Save a reusable experience/decision/knowledge |
| `nexus_feedback(ids, useful)` | Tell NEXUS what helped (adjusts ranking) |
| `nexus_revalidate(id)` | Confirm a stale entry still holds |
| `nexus_link(src, dst, type)` | Add a typed relation |
| `nexus_capabilities(kind?)`, `nexus_status()`, `nexus_sync()` | Inventory and health |

## CLI

`nexus sync | status | doctor | route | search | show | remember | capabilities [--redundant] | forget | restore-version | backup | restore | install | uninstall | mcp | hook`

## Privacy and safety

- Everything is local (`~/.nexus/nexus.db`, SQLite). No telemetry, no network calls.
- Read-only on Claude Code files, except `nexus install`/`uninstall`, which edit `settings.json` after backing it up.
- MCP server `env` values are never stored, only their key names.
- `remember` refuses content that looks like a secret (private keys, API tokens, `password=`…).
- Everything NEXUS returns is labelled as untrusted data, never instructions.
- Every change to an entry is versioned; `forget` and edits are reversible with `restore-version`.
- Hooks fail open: if NEXUS breaks, Claude Code starts normally and the error goes to `~/.nexus/hook-errors.log`.

## Honest limits

- NEXUS **recommends**; Claude decides what to load. It cannot force a skill or tool.
- Token figures are **estimates** (≈ 4 chars/token). Real token usage is not observable from hooks or MCP.
- Matching is lexical (BM25 + term coverage + a small FR→EN glossary). Synonyms that share no words can be missed; optional local embeddings are planned once a benchmark shows the need.
- Built-in Claude Code commands (e.g. `/code-review`) are not files on disk and are not discovered.

## Development

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Linux/macOS: .venv/bin/pip
.venv/Scripts/python -m pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## License

Apache-2.0
