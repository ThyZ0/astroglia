"""Value scenarios: the same questions answered without Astroglia, with a plain notes file, and with Astroglia.

    python bench/value.py <demo-dir>        (build it first: python bench/demo_seed.py <demo-dir>)

Reproducible on the demo dataset. Baselines are stated assumptions, printed with the results:
- onboarding without Astroglia: the agent lists the project tree and reads the README and every manifest once;
- recall with a notes file: every remembered entry is a paragraph in one Markdown file, found by keyword
  search (all query words present, like grep); the file cannot say whether a note is still true.
Tokens are estimates (characters / 4).
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astroglia import brief, config, providers, router  # noqa: E402
from astroglia.store import Store  # noqa: E402
from astroglia.text import est_tokens, terms  # noqa: E402

RECALL = [  # question, the entry that answers it
    ("cart total wrong with discount codes", "Cart total drifted with discount codes"),
    ("stripe checkout retries charge twice", "Checkout uses Stripe idempotency keys"),
    ("forecast provider rate limit cache", "Forecast cache TTL is 10 minutes"),
    ("weather provider times out under load", "Flaky provider timeouts"),
]


def onboarding(root: Path, store: Store, name: str) -> dict:
    listing = "\n".join(str(p.relative_to(root)) for p in brief._walk(root))
    b = brief.build(root)
    read = [Path(f) for f in b["files"]]
    without = est_tokens(listing) + sum(est_tokens(p.read_text(encoding="utf-8", errors="replace")) for p in read)
    node = store.get(f"knowledge:brief:{name}")
    return {"project": name, "without_reads": 1 + len(read), "without_tokens": without,
            "with_reads_manifest_only": 0, "with_tokens_manifest_line": est_tokens(node["summary"][:300]),
            "with_reads_full_brief": 1, "with_tokens_full_brief": est_tokens(node["body"])}


def recall(store: Store, cfg) -> dict:
    mem = [n for n in store.nodes() if n["kind"] in ("experience", "decision") ]
    notes = [(n["title"], f"{n['title']}. {n['summary']} {n['body'] or ''}".lower()) for n in mem]
    grep_hits = route_hits = 0
    for q, want in RECALL:
        words = set(terms(q))
        grep_hits += any(t == want and all(w in text for w in words) for t, text in notes)
        sel = router.route(store, cfg, q, log=False)["selected"]
        route_hits += bool(sel) and sel[0]["title"] == want
    stale = [n["title"] for n in mem if n["status"] == "stale"]
    from astroglia import anchors
    anchored = 0
    for n in mem:  # served by merely reading one of the entry's files: no query, no tool call by Claude
        f = next(iter(n["fingerprint"] or {}), None)
        out = f and anchors.respond({"tool_name": "Read", "tool_input": {"file_path": f}, "session_id": "bench-" + n["id"]}, cfg.db_path)
        anchored += bool(out) and n["id"] in out
    return {"questions": len(RECALL), "notes_file_found": grep_hits, "astroglia_found_first": route_hits,
            "stale_entries": len(stale), "notes_file_can_flag_stale": 0, "astroglia_flags_stale": len(stale),
            "served_on_file_read_without_query": f"{anchored}/{len(mem)}"}


def main(base: Path) -> None:
    os.environ["CLAUDE_CONFIG_DIR"] = str(base / "claude")
    providers.cortex_projects = lambda: []
    cfg = config.load(base / "home")
    cfg.claude_json = base / ".claude.json"
    store = Store(cfg.db_path)
    rows = [onboarding(base / "projects" / p, store, p) for p in ("acme-shop", "weather-api", "log-crunch")]
    out = {"assumptions": __doc__.split("Baselines are stated assumptions, printed with the results:")[1].strip(),
           "onboarding": rows, "recall": recall(store, cfg)}
    print(json.dumps(out, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
