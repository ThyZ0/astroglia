"""Brain health and suggestions, from explicit rules over the store (no guesses presented as facts).

- overlaps: memory entries that say nearly the same thing (duplicates, or contradictions to review)
- missing relations: an entry names a capability or project it is not linked to
- unused capabilities: never selected or fetched although routing has been used enough to tell
- most served: what Claude actually reuses
- health score: four ratios, each explained
"""
from __future__ import annotations

import json
import re

from .capabilities import similarity
from .store import Store
from .text import STOP

COMMON_WORDS = {"update", "start", "review", "search", "memory", "debug", "deploy", "build", "plan", "tests", "docs",
                "learn", "preferences", "morning", "github", "browser", "notes", "simplify", "loop", "schedule", "init"}

MEMORY = ("experience", "decision", "knowledge")
WORK = ("skill", "command", "agent", "mcp_server")
MIN_ROUTINGS_FOR_UNUSED = 10


def _dismissed(store: Store) -> set[str]:
    return set(json.loads(store.kv_get("dismissed_suggestions", "[]")))


def dismiss(store: Store, key: str) -> None:
    d = _dismissed(store)
    d.add(key)
    store.kv_set("dismissed_suggestions", json.dumps(sorted(d)))
    store.log("insight.dismissed", key=key)


def overlaps(store: Store, threshold: float = 0.5) -> list[dict]:
    mem = [n for n in store.nodes() if n["kind"] in MEMORY and n["status"] != "missing"
           and not n["id"].startswith(("knowledge:brief:", "knowledge:claude-md:"))]
    out, gone = [], _dismissed(store)
    for i, a in enumerate(mem):
        for b in mem[i + 1:]:
            s = similarity(a["title"] + " " + a["summary"], b["title"] + " " + b["summary"])
            key = f"overlap:{a['id']}|{b['id']}"
            if s >= threshold and key not in gone:
                out.append({"key": key, "a": {"id": a["id"], "title": a["title"]}, "b": {"id": b["id"], "title": b["title"]},
                            "similarity": round(s, 2),
                            "advice": "Same knowledge twice, or two versions that disagree: read both, then merge or fix one."})
    return sorted(out, key=lambda x: -x["similarity"])


def missing_relations(store: Store) -> list[dict]:
    nodes = store.nodes(status="active")
    # distinctive names only: "code-review", "graphify", a project name; never plain words like "update" or "docs"
    targets = [n for n in nodes if (n["kind"] in WORK + ("plugin",) or n["kind"] == "project")
               and len(n["title"]) >= 5 and n["title"].lower() not in COMMON_WORDS and n["title"].lower() not in STOP]
    linked = {(e["src"], e["dst"]) for e in store.edges()} | {(e["dst"], e["src"]) for e in store.edges()}
    out, gone = [], _dismissed(store)
    for n in nodes:
        if n["kind"] not in MEMORY or n["source"].startswith(("provider:", "scan:")):
            continue  # only what Claude or the user wrote: generated briefs and pointers are not claims
        text = " " + " ".join(filter(None, (n["title"], n["summary"], n["body"] or ""))).lower() + " "
        for t in targets:
            if t["id"] == n["id"] or (n["id"], t["id"]) in linked or (n["kind"] != "project" and t["kind"] == "project" and n["project"] == t["title"]):
                continue
            if re.search(rf"(?<![\w-]){re.escape(t['title'].lower())}(?![\w-])", text):
                key = f"link:{n['id']}|{t['id']}"
                if key not in gone:
                    out.append({"key": key, "src": {"id": n["id"], "title": n["title"]}, "dst": {"id": t["id"], "title": t["title"], "kind": t["kind"]},
                                "type": "related_to", "why": f"“{n['title']}” mentions “{t['title']}” but is not linked to it."})
    return out


def usage(store: Store) -> tuple[dict, int]:
    counts, routings = {}, 0
    for kind, raw in store.db.execute("SELECT kind, payload FROM events WHERE kind IN ('route', 'served')").fetchall():
        p = json.loads(raw)
        if kind == "route":
            routings += 1
            for i in p.get("selected", []):
                counts[i] = counts.get(i, 0) + 1
        elif p.get("id"):
            counts[p["id"]] = counts.get(p["id"], 0) + 1
    return counts, routings


def report(store: Store) -> dict:
    counts, routings = usage(store)
    nodes = store.nodes()
    active = [n for n in nodes if n["status"] in ("active", "stale")]
    mem = [n for n in active if n["kind"] in MEMORY and not n["id"].startswith("knowledge:claude-md:")]
    linked = {e["src"] for e in store.edges()} | {e["dst"] for e in store.edges()}
    projects = [n for n in active if n["kind"] == "project"]
    documented = {n["project"] for n in mem}
    ratio = lambda part, whole: round(part / whole, 3) if whole else 1.0
    parts = {
        "freshness": {"value": ratio(sum(n["status"] != "stale" for n in mem), len(mem)),
                      "means": "share of memory whose source files are unchanged since recorded"},
        "verifiability": {"value": ratio(sum(bool(n["fingerprint"]) for n in mem), len(mem)),
                          "means": "share of memory tied to source files (so staleness can be detected)"},
        "connectivity": {"value": ratio(sum(n["id"] in linked for n in active), len(active)),
                         "means": "share of entries linked to at least one other"},
        "documentation": {"value": ratio(sum(p["title"] in documented for p in projects), len(projects)),
                          "means": "share of projects with a brief or remembered knowledge"},
    }
    unused = []
    if routings >= MIN_ROUTINGS_FOR_UNUSED:
        unused = [{"id": n["id"], "title": n["title"], "kind": n["kind"]} for n in active
                  if n["kind"] in WORK and n["status"] == "active" and not counts.get(n["id"])]
    top = sorted(((c, i) for i, c in counts.items() if store.get(i)), reverse=True)[:8]
    return {
        "score": round(100 * sum(p["value"] for p in parts.values()) / len(parts)),
        "parts": parts,
        "overlaps": overlaps(store),
        "missing_relations": missing_relations(store),
        "unused_capabilities": unused,
        "unused_note": None if routings >= MIN_ROUTINGS_FOR_UNUSED else
        f"Needs at least {MIN_ROUTINGS_FOR_UNUSED} routings to tell what is never used ({routings} so far).",
        "most_served": [{"id": i, "title": store.get(i)["title"], "kind": store.get(i)["kind"], "times": c} for c, i in top],
        "routings": routings,
    }
