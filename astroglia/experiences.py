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


def fingerprint(files: list[str]) -> dict:
    return {str(Path(f).resolve()): sha256(Path(f)) for f in files}


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
    fp = fingerprint(list(files))
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
    return {"id": nid, "result": result}


def verify(store: Store, node_id: str) -> dict:
    """Re-hash source files. Returns {'status', 'changed': [...]}; updates the node."""
    n = store.get(node_id)
    if n is None:
        raise KeyError(node_id)
    fp = n["fingerprint"] or {}
    changed = [f for f, h in fp.items() if h is None or sha256(Path(f)) != h]  # a missing file is a change
    if not fp:
        return {"status": n["status"], "changed": [], "note": "no source files recorded; cannot verify"}
    if changed:
        if n["status"] != "stale":
            store.set_status(node_id, "stale", op="verify", changed_files=changed)
            store.log("memory.stale", id=node_id, changed=changed)
        return {"status": "stale", "changed": changed}
    if n["status"] == "stale":
        store.set_status(node_id, "active", op="verify", changed_files=[])
    else:
        store.upsert({"id": node_id, "verified": now()})
    return {"status": "active", "changed": []}


def revalidate(store: Store, node_id: str) -> dict:
    """Agent confirmed the entry still holds after the sources changed: accept current file hashes."""
    n = store.get(node_id)
    if n is None:
        raise KeyError(node_id)
    fp = fingerprint(list((n["fingerprint"] or {}).keys()))
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
    for n in store.db.execute("SELECT id FROM nodes WHERE fingerprint IS NOT NULL AND status IN ('active','stale')"):
        out["checked"] += 1
        if verify(store, n["id"])["status"] == "stale":
            out["stale"].append(n["id"])
    return out
