"""Routing benchmark: does the router put the right resource first, and at what cost?

Compares the full router with a plain BM25 baseline over the same index.
Labels are a JSON file: {"tasks": [{"task": str, "expect": [ids], "project"?: str}]}.
A task is a hit at k if ANY expected id is in the top k.
"""
from __future__ import annotations

import json
import statistics
import time
from pathlib import Path

from . import router
from .config import Config
from .experiences import MEMORY_KINDS
from .store import Store
from .text import fts_query


def _rank(ids: list[str], expect: set[str]) -> int:
    return next((i + 1 for i, x in enumerate(ids) if x in expect), 0)


def run(store: Store, cfg: Config, labels: str | Path) -> dict:
    tasks = json.loads(Path(labels).read_text(encoding="utf-8"))["tasks"]
    # Labels that expect only capabilities measure capability routing: memory written later (notes about the
    # work itself, briefs) would otherwise compete and make the score drift with the store's contents.
    expects_memory = any(i.split(":", 1)[0] in MEMORY_KINDS for t in tasks for i in t["expect"])
    kinds = None if expects_memory else [k for k in store.stats()["nodes_by_kind"]
                                         if k not in MEMORY_KINDS and k not in router.DEFAULT_EXCLUDED_KINDS]
    rows, lat = [], []
    for t in tasks:
        expect = set(t["expect"])
        t0 = time.perf_counter()
        r = router.route(store, cfg, t["task"], project=t.get("project"), kinds=kinds, log=False)
        lat.append((time.perf_counter() - t0) * 1000)
        ids = [s["id"] for s in r["selected"]]
        q = fts_query(t["task"])
        base = [i for i, _ in store.fts(q)] if q else []
        base = [i for i in base if (n := store.get(i)) and n["kind"] not in router.DEFAULT_EXCLUDED_KINDS
                and (kinds is None or n["kind"] in kinds)]
        rows.append({"task": t["task"], "rank": _rank(ids, expect), "baseline_rank": _rank(base, expect),
                     "recall": len(set(ids) & expect) / len(expect),
                     "selected": len(ids), "est_tokens": r["estimated_tokens"], "top": ids[:3]})

    def metrics(key: str) -> dict:
        ranks = [x[key] for x in rows]
        return {"hit@1": sum(r == 1 for r in ranks) / len(ranks),
                "hit@3": sum(0 < r <= 3 for r in ranks) / len(ranks),
                "mrr": sum(1 / r for r in ranks if r) / len(ranks)}

    return {
        "tasks": len(rows),
        "router": metrics("rank"),
        "baseline_bm25": metrics("baseline_rank"),
        "router_latency_ms": {"p50": round(statistics.median(lat), 1),
                              "max": round(max(lat), 1)},
        "recall_expected": round(statistics.mean(x["recall"] for x in rows), 3),  # share of all expected resources returned
        "avg_selected": round(statistics.mean(x["selected"] for x in rows), 2),
        "avg_est_tokens": round(statistics.mean(x["est_tokens"] for x in rows)),
        "misses": [{"task": x["task"], "top": x["top"]} for x in rows if x["rank"] != 1],
        "scope": "all kinds" if kinds is None else "capabilities only (labels expect no memory entries)",
        "note": "Tokens are estimates (chars/4). Labels are human judgements for one install.",
    }
