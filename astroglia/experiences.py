"""Experience & knowledge engine: things the agent learned, tied to the sources they depend on.

An entry records the sha256 of the files it was derived from. When any of them changes
or disappears the entry is flagged `stale` instead of being served as still valid.
"""
from __future__ import annotations

import hashlib
import re
import uuid
from pathlib import Path

from .store import Store, now

MEMORY_KINDS = ("experience", "decision", "knowledge", "project")

_SECRET_PATTERNS = [
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),                       # AWS access key id
    re.compile(r"\b(sk|rk|pk)-[A-Za-z0-9_-]{20,}\b"),          # common API key prefixes
    re.compile(r"\bgh[pousr]_[A-Za-z0-9]{30,}\b"),             # GitHub tokens
    re.compile(r"\bxox[abpr]-[A-Za-z0-9-]{10,}\b"),            # Slack tokens
    re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\s*[:=]\s*['\"]?[^\s'\"]{8,}"),
]


def find_secret(text: str) -> str | None:
    for p in _SECRET_PATTERNS:
        m = p.search(text or "")
        if m:
            return p.pattern
    return None


def sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def cached_sha256(store: Store | None, path: Path) -> str | None:
    """sha256 of a file, re-read only when its size or mtime changed since the last hash."""
    try:
        st = path.stat()
    except OSError:
        return None
    if store is not None:
        r = store.db.execute("SELECT size, mtime_ns, sha256 FROM file_cache WHERE path=?", (str(path),)).fetchone()
        if r and r["size"] == st.st_size and r["mtime_ns"] == st.st_mtime_ns:
            return r["sha256"]
    h = sha256(path)
    if store is not None and h:
        store.db.execute("INSERT INTO file_cache(path,size,mtime_ns,sha256) VALUES(?,?,?,?) ON CONFLICT(path) DO UPDATE SET "
                         "size=excluded.size, mtime_ns=excluded.mtime_ns, sha256=excluded.sha256", (str(path), st.st_size, st.st_mtime_ns, h))
        store.db.commit()
    return h


def fingerprint(files: list[str], store: Store | None = None) -> dict:
    return {str(Path(f).resolve()): cached_sha256(store, Path(f).resolve()) for f in files}


def similar_entries(store: Store, title: str, summary: str, exclude: str | None = None, limit: int = 3) -> list[dict]:
    """Existing memory that looks like the same thing (to update instead of duplicating)."""
    from .capabilities import similarity
    from .text import fts_query
    q = fts_query(title + " " + summary)
    out = []
    for nid, _ in (store.fts(q, limit=20) if q else []):
        n = store.get(nid)
        if not n or nid == exclude or n["kind"] not in MEMORY_KINDS[:3]:
            continue
        sim = similarity(title + " " + summary, n["title"] + " " + n["summary"])
        if sim >= 0.4:
            out.append({"id": nid, "title": n["title"], "similarity": round(sim, 2)})
    return sorted(out, key=lambda x: -x["similarity"])[:limit]


def remember(store: Store, title: str, summary: str, body: str = "", kind: str = "experience",
             project: str | None = None, tags: list[str] | str = (), files: list[str] = (),
             confidence: float = 0.7, importance: float = 0.5, source: str = "agent",
             related: list[str] = (), node_id: str | None = None) -> dict:
    if kind not in MEMORY_KINDS:
        raise ValueError(f"kind must be one of {MEMORY_KINDS}")
    if not title.strip() or not summary.strip():
        raise ValueError("title and summary are required")
    hit = find_secret("\n".join((title, summary, body)))
    if hit:
        raise ValueError(f"refused: content looks like it contains a secret (pattern {hit}). Remove it and retry.")
    fp = fingerprint(list(files), store)
    missing = [f for f, h in fp.items() if h is None]
    if missing:
        raise ValueError(f"source files not found: {missing}")
    nid = node_id or f"{kind}:{uuid.uuid4().hex[:12]}"
    tags = tags if isinstance(tags, str) else " ".join(tags)
    result = store.upsert({
        "id": nid, "kind": kind, "title": title.strip(), "summary": summary.strip(), "body": body or None,
        "source": source, "project": project, "tags": tags, "confidence": float(confidence),
        "importance": float(importance), "status": "active", "fingerprint": fp or None,
        "verified": now(), "meta": {"files": list(fp)},
    }, op="remember")
    for r in related:
        if store.get(r):
            store.link(nid, r, "related_to", source=source, confidence=0.8)
    if project:
        pid = f"project:{project}"
        if not store.get(pid):
            store.upsert({"id": pid, "kind": "project", "title": project, "summary": f"Project {project}",
                          "source": source, "project": project, "confidence": 0.9})
        store.link(nid, pid, "belongs_to", source=source, confidence=1.0)
    store.log("memory." + result, id=nid, kind=kind, title=title)
    out = {"id": nid, "result": result}
    if not node_id:
        sim = similar_entries(store, title, summary, exclude=nid)
        if sim:
            store.log("memory.similar", id=nid, similar=[x["id"] for x in sim])
            out["similar_existing"] = sim
            out["hint"] = "Similar entries already exist: if this is the same knowledge, update one of them (node_id) and forget this one."
    return out


def verify(store: Store, node_id: str, commit: bool = True) -> dict:
    """Re-hash source files (cached by size+mtime). Returns {'status', 'changed': [...]}; updates the node.
    commit=False lets verify_all check everything in one transaction."""
    n = store.get(node_id)
    if n is None:
        raise KeyError(node_id)
    fp = n["fingerprint"] or {}
    changed = [f for f, h in fp.items() if h is None or cached_sha256(store, Path(f)) != h]  # a missing file is a change
    if not fp:
        return {"status": n["status"], "changed": [], "note": "no source files recorded; cannot verify"}
    if changed:
        if n["status"] != "stale":
            store.set_status(node_id, "stale", op="verify", changed_files=changed)
            store.log("memory.stale", id=node_id, changed=changed)
        return {"status": "stale", "changed": changed}
    if n["status"] == "stale":
        store.set_status(node_id, "active", op="verify", changed_files=[])
    else:  # unchanged: only the verification date moves (no history entry, no per-entry commit)
        store.db.execute("UPDATE nodes SET verified=? WHERE id=?", (now(), node_id))
        if commit:
            store.db.commit()
    return {"status": "active", "changed": []}


def revalidate(store: Store, node_id: str) -> dict:
    """Agent confirmed the entry still holds after the sources changed: accept current file hashes."""
    n = store.get(node_id)
    if n is None:
        raise KeyError(node_id)
    fp = fingerprint(list((n["fingerprint"] or {}).keys()), store)
    gone = [f for f, h in fp.items() if h is None]
    if gone:  # a deleted source cannot be "still valid": the entry must be updated with its new files
        raise ValueError(f"source files no longer exist: {gone}. Update the entry (remember with node_id) with the current files.")
    meta = n["meta"]; meta["changed_files"] = []
    store.upsert({"id": node_id, "status": "active", "fingerprint": fp or None, "verified": now(), "meta": meta},
                 op="revalidate")
    store.log("memory.revalidated", id=node_id)
    return {"status": "active"}


def verify_all(store: Store) -> dict:
    out = {"checked": 0, "stale": []}
    ids = [r["id"] for r in store.db.execute("SELECT id FROM nodes WHERE fingerprint IS NOT NULL AND status IN ('active','stale')")]
    for nid in ids:
        out["checked"] += 1
        if verify(store, nid, commit=False)["status"] == "stale":
            out["stale"].append(nid)
    store.db.commit()
    return out
