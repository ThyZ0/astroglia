# Contributing to Astroglia

Thanks for helping. Astroglia's rule is simple: **every feature must make Claude's work measurably better.** A pretty feature with no use is declined; a dull one that saves real time is welcome.

## Set up

```bash
git clone https://github.com/OWNER/astroglia && cd astroglia
python -m venv .venv
.venv/Scripts/pip install -e ".[dev]"     # Linux/macOS: .venv/bin/pip
python -m pytest
```

Try the UI on the demo dataset (never on someone else's data):

```bash
python bench/demo_seed.py /tmp/astroglia-demo
astroglia --home /tmp/astroglia-demo/home ui
```

## Ground rules

- **No fake data, no simulated activity.** UI animations come only from the event log. Estimates are labelled with their formula.
- **Measure before claiming.** Routing changes come with `astroglia bench bench/local-tasks.json` before/after numbers in the PR (relabel the file for your install). Performance changes come with `python bench/load.py` numbers.
- **Local first.** No network calls or telemetry in the core.
- **Reversible.** Every mutation goes through `Store` methods (versioned in `history`, logged in `events`).
- **Hooks fail open.** A broken Astroglia must never block Claude Code.
- **Standard library first.** A new dependency needs a reason in the PR.
- **Schema changes:** bump `SCHEMA_VERSION` in `astroglia/store.py`, add a migration step (never edit an old one) and a test.

## Where things live

| Path | What |
|---|---|
| `astroglia/capabilities.py` | discovery of skills, plugins, MCP servers, agents, hooks |
| `astroglia/router.py` | `route`: scoring, cuts, explanations |
| `astroglia/experiences.py` | `remember`, freshness (`verify`, `revalidate`), secret refusal |
| `astroglia/providers.py`, `brief.py` | project cards, Cortex/Graphify pointers, project briefs |
| `astroglia/hooks.py` | SessionStart manifest, Stop consolidation |
| `astroglia/web.py`, `ui/` | local UI (plain HTML/CSS/JS, no build step) |
| `bench/` | routing benchmark labels, load benchmark, demo dataset |

## Pull requests

Small, one topic, tests included, `CHANGELOG.md` updated under *Unreleased*. Describe what problem it solves for a Claude Code user.
