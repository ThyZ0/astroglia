"""Value report: what Astroglia actually served, counted from its own event log.

Measured = counted events. Estimated = derived with a stated formula; always labelled as such.
"""
from __future__ import annotations

import json

from .store import Store

MEMORY = {"experience", "decision", "knowledge"}


def value(store: Store, days: int | None = None) -> dict:
    q = "SELECT kind, payload FROM events" + (" WHERE ts >= ?" if days else "")
    args = ()
    if days:
        from datetime import datetime, timedelta, timezone
        args = ((datetime.now(timezone.utc) - timedelta(days=days)).isoformat(timespec="seconds"),)
    m = dict.fromkeys(("routings", "routings_with_results", "memory_served", "briefs_served", "anchored_served", "stale_warnings",
                       "project_cards_served", "entries_fetched", "memories_saved", "duplicates_flagged",
                       "consolidations_asked", "feedback_useful", "feedback_not_useful", "sessions"), 0)
    brief_bytes = 0
    for kind, raw in store.db.execute(q, args).fetchall():
        p = json.loads(raw)
        if kind == "route":
            m["routings"] += 1
            served = p.get("served") or [{"id": i, "kind": i.split(":", 1)[0], "stale": False} for i in p.get("selected", [])]
            m["routings_with_results"] += bool(served)
            for s in served:
                if s["id"].startswith("knowledge:brief:"):
                    m["briefs_served"] += 1
                elif s["kind"] in MEMORY:
                    m["memory_served"] += 1
                m["stale_warnings"] += bool(s.get("stale"))
        elif kind == "served":
            if p.get("kind") == "brief":
                m["briefs_served"] += 1
                brief_bytes += p.get("bytes", 0)
            elif p.get("kind") == "anchor":
                m["anchored_served"] += p.get("count", 1)
            elif p.get("kind") == "project_card":
                m["project_cards_served"] += 1
                m["stale_warnings"] += p.get("stale", 0)
            else:
                m["entries_fetched"] += 1
                m["stale_warnings"] += bool(p.get("stale"))
        elif kind == "memory.created":
            m["memories_saved"] += 1
        elif kind == "memory.similar":
            m["duplicates_flagged"] += 1
        elif kind == "consolidate.asked":
            m["consolidations_asked"] += 1
        elif kind == "feedback":
            m["feedback_useful" if p.get("useful") else "feedback_not_useful"] += len(p.get("ids", []))
        elif kind == "wake":
            m["sessions"] += 1
    return {"period_days": days, "measured": m,
            "estimated": {"tokens_of_rereading_avoided_by_briefs": brief_bytes // 4,
                          "formula": "bytes of the source files each served brief summarises / 4 chars per token; assumes "
                                     "the agent would otherwise read those files once per session (an upper bound)"}}
