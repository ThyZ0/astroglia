"""Context Router: picks the few resources worth loading for a task, and says why.

Deterministic: FTS5/BM25 candidates, then a weighted score from metadata
(confidence, freshness, observed success, project match), then greedy selection
that drops redundant capabilities and respects a token budget. No LLM call.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone

from .config import Config
from .experiences import verify
from .store import Store
from .text import est_tokens, fts_query, terms

SKIP_STATUS = ("missing", "disabled", "archived")
# Plugins are containers of skills (routing them duplicates their skills); hooks run on their own.
DEFAULT_EXCLUDED_KINDS = ("plugin", "hook")
POINTER_OVERHEAD = 12  # tokens for id/kind/ref framing of one pointer (estimate)


def _age_days(ts: str) -> float:
    try:
        return max(0.0, (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds() / 86400)
    except (TypeError, ValueError):
        return 365.0


def route(store: Store, cfg: Config, task: str, project: str | None = None, budget: int = 1200,
          kinds: list[str] | None = None, limit: int = 12) -> dict:
    match = fts_query(task)
    result = {"task": task, "selected": [], "rejected": [], "estimated_tokens": 0, "budget": budget,
              "note": "Pointers only. Fetch full content with nexus_get(id) when needed. Token counts are estimates."}
    if not match:
        result["note"] = "Task has no searchable terms."
        return result
    hits = store.fts(match)
    if not hits:
        store.log("route", task=task[:300], selected=[], rejected=0)
        return result
    best = min(s for _, s in hits)  # bm25: lower (more negative) is better
    w = cfg.weights
    qterms = set(terms(task))
    cands = []
    for nid, s in hits:
        n = store.get(nid)
        if n is None or n["status"] in SKIP_STATUS:
            continue
        if (kinds and n["kind"] not in kinds) or (not kinds and n["kind"] in DEFAULT_EXCLUDED_KINDS):
            continue
        # Relative BM25 rank alone always gives the top hit 1.0; blend with absolute term coverage.
        nterms = set(terms(" ".join(filter(None, (n["title"], n["summary"], n["tags"], n["body"])))))
        covered = sum(1 for t in qterms if any(x.startswith(t[:5]) for x in nterms)) / max(1, len(qterms))
        rel = 0.5 * (s / best if best < 0 else 0.0) + 0.5 * covered
        fresh = 0.5 ** (_age_days(n["verified"]) / cfg.half_life_days)
        succ = (n["successes"] + 1) / (n["uses"] + 2)
        proj = 1.0 if project and n["project"] and project.lower() in n["project"].lower() else 0.0
        parts = {"relevance": rel, "confidence": n["confidence"], "freshness": fresh, "success": succ, "project": proj}
        score = sum(w.get(k, 0) * v for k, v in parts.items())
        cands.append((score, n, parts))
    cands.sort(key=lambda c: -c[0])

    similar = {}
    for e in store.edges(type="similar_to"):
        similar.setdefault(e["src"], {})[e["dst"]] = e["confidence"]
        similar.setdefault(e["dst"], {})[e["src"]] = e["confidence"]

    chosen, per_kind, used = [], {}, 0
    for score, n, parts in cands:
        why = {k: round(v, 3) for k, v in parts.items()}
        entry = {"id": n["id"], "kind": n["kind"], "title": n["title"], "score": round(score, 3)}
        if len(chosen) >= limit:
            result["rejected"].append({**entry, "reason": "limit reached"}); continue
        if score < cfg.min_score:
            result["rejected"].append({**entry, "reason": f"score below min_score {cfg.min_score}"}); continue
        dup = next((c for c in chosen if similar.get(n["id"], {}).get(c["id"], 0) >= cfg.redundancy_threshold), None)
        if dup:
            result["rejected"].append({**entry, "reason": f"redundant with {dup['id']} "
                                       f"(similarity {similar[n['id']][dup['id']]:.2f}, lower score)"}); continue
        if per_kind.get(n["kind"], 0) >= cfg.max_per_kind:
            result["rejected"].append({**entry, "reason": f"max_per_kind {cfg.max_per_kind} reached for {n['kind']}"}); continue
        summary = n["summary"][:400]
        cost = est_tokens(n["title"] + summary) + POINTER_OVERHEAD
        if used + cost > budget:
            result["rejected"].append({**entry, "reason": f"budget: needs ~{cost} tokens, {budget - used} left"}); continue
        warnings = []
        if n["fingerprint"]:
            v = verify(store, n["id"])
            if v["status"] == "stale":
                warnings.append(f"STALE: source files changed since recorded: {v['changed'][:5]}. Re-check before relying on it.")
                score *= 0.6
        if n["confidence"] < 0.5:
            warnings.append("low confidence")
        see_also = sorted({e["dst"] if e["src"] == n["id"] else e["src"] for e in store.edges(n["id"])
                           if e["type"] in ("related_to", "similar_to", "complements", "replaces")})
        chosen.append({**entry, "score": round(score, 3), "summary": summary, "ref": n["ref"], "project": n["project"],
                       "has_body": bool(n["body"]), "why": why, "warnings": warnings, "see_also": see_also[:5]})
        per_kind[n["kind"]] = per_kind.get(n["kind"], 0) + 1
        used += cost

    result["selected"] = chosen
    result["estimated_tokens"] = used
    result["route_id"] = store.log("route", task=task[:300], project=project,
                                   selected=[c["id"] for c in chosen],
                                   rejected=[{"id": r["id"], "reason": r["reason"]} for r in result["rejected"][:30]],
                                   estimated_tokens=used)
    return result


def feedback(store: Store, ids: list[str], useful: bool) -> dict:
    """Adaptation v0: record whether routed resources helped. Reversible (counters only, logged)."""
    for i in ids:
        store.bump(i, uses=1, successes=1 if useful else 0)
    store.log("feedback", ids=ids, useful=useful)
    return {"recorded": len(ids)}
