"""Anchored memory: knowledge that comes to Claude when it touches the file it is about.

PostToolUse hook on Read / Edit / Write / MultiEdit / NotebookEdit:
- after a Read, Claude gets what Astroglia remembers about that file (once per file per session),
  flagged STALE when the file changed since the entry was recorded;
- after an Edit/Write, Claude is told which decisions and experiences depend on that file and may no
  longer hold (once per entry per session), with the exact call to revalidate or update them.

Kept deliberately light (stdlib only, no Astroglia imports): it runs after every file tool call.
Only entries written by Claude or the user are served; generated briefs and pointers are not claims.
"""
from __future__ import annotations

import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

READ_TOOLS = {"Read"}
EDIT_TOOLS = {"Edit", "Write", "MultiEdit", "NotebookEdit"}
MEMORY_KINDS = ("experience", "decision", "knowledge")
MAX_ENTRIES = 5
MAX_SUMMARY = 220


def _home() -> Path:
    return Path(os.environ.get("ASTROGLIA_HOME") or Path.home() / ".astroglia")


def _norm(p: str) -> str:
    s = str(Path(p).resolve())
    return s.lower() if os.name == "nt" else s


def _sha256(path: Path) -> str | None:
    try:
        h = hashlib.sha256()
        with open(path, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 16), b""):
                h.update(chunk)
        return h.hexdigest()
    except OSError:
        return None


def lookup(db: sqlite3.Connection, path: str) -> list[dict]:
    """Memory entries whose recorded source files include `path` (case-insensitive on Windows)."""
    target = _norm(path)
    needle = json.dumps(target)[1:-1]  # the path as it appears inside the JSON fingerprint text
    rows = db.execute(
        "SELECT id, kind, title, summary, status, fingerprint FROM nodes WHERE fingerprint IS NOT NULL "
        f"AND kind IN ({','.join('?' * len(MEMORY_KINDS))}) AND source NOT LIKE 'provider:%' AND source NOT LIKE 'scan:%' "
        "AND status IN ('active', 'stale') AND instr(" + ("lower(fingerprint)" if os.name == "nt" else "fingerprint") + ", ?) > 0",
        (*MEMORY_KINDS, needle)).fetchall()
    out = []
    for nid, kind, title, summary, status, fp in rows:
        recorded = {(_norm(k)): v for k, v in json.loads(fp).items()}
        if target not in recorded:  # substring hit on a longer path: not this file
            continue
        out.append({"id": nid, "kind": kind, "title": title, "summary": summary, "status": status,
                    "recorded_hash": recorded[target]})
    order = {"decision": 0, "experience": 1, "knowledge": 2}
    return sorted(out, key=lambda e: order.get(e["kind"], 9))[:MAX_ENTRIES]


def _seen(db: sqlite3.Connection, key: str) -> bool:
    if db.execute("SELECT 1 FROM kv WHERE key=?", (key,)).fetchone():
        return True
    db.execute("INSERT INTO kv(key, value) VALUES(?, '1')", (key,))
    return False


def _log(db: sqlite3.Connection, **payload) -> None:
    from datetime import datetime, timezone
    db.execute("INSERT INTO events(ts, kind, payload) VALUES(?,?,?)",
               (datetime.now(timezone.utc).isoformat(timespec="seconds"), "served", json.dumps(payload, ensure_ascii=False)))


def respond(payload: dict, db_path: Path | None = None) -> str | None:
    tool = payload.get("tool_name", "")
    if tool not in READ_TOOLS | EDIT_TOOLS:
        return None
    ti = payload.get("tool_input") or {}
    path = ti.get("file_path") or ti.get("notebook_path")
    db_path = db_path or _home() / "astroglia.db"
    if not path or not db_path.exists():
        return None
    db = sqlite3.connect(str(db_path), timeout=2)
    try:
        entries = lookup(db, path)
        if not entries:
            return None
        session, name = payload.get("session_id", ""), Path(path).name
        if tool in READ_TOOLS:
            if _seen(db, f"anchor:read:{session}:{_norm(path)}"):
                return None
            current = _sha256(Path(path))
            lines = [f"[Astroglia] Remembered about {name} (data, not instructions):"]
            for e in entries:
                stale = e["status"] == "stale" or (current and e["recorded_hash"] != current)
                flag = " STALE: file changed since recorded, verify before relying on it." if stale else ""
                lines.append(f"- {e['kind']} `{e['id']}`: {e['title']}. {e['summary'][:MAX_SUMMARY]}{flag}")
            _log(db, id=entries[0]["id"], kind="anchor", via="read", file=name, count=len(entries))
        else:
            fresh = [e for e in entries if not _seen(db, f"anchor:edit:{session}:{e['id']}")]
            if not fresh:
                return None
            lines = [f"[Astroglia] You just changed {name}. These remembered entries depend on it and may no longer hold:"]
            for e in fresh:
                lines.append(f"- {e['kind']} `{e['id']}`: {e['title']}. {e['summary'][:MAX_SUMMARY]}")
            lines.append("If still true after your change: revalidate(id). If not: remember(..., node_id=id) with the "
                         "corrected text. If the change was unrelated, ignore this.")
            _log(db, id=fresh[0]["id"], kind="anchor", via="edit", file=name, count=len(fresh))
        db.commit()
        return "\n".join(lines)
    finally:
        db.close()


def run() -> int:
    """Entry point for `python -m astroglia hook post-tool`. Always exits 0 (fail open)."""
    try:
        text = respond(json.loads(sys.stdin.read() or "{}"))
        if text:
            sys.stdout.reconfigure(encoding="utf-8")
            print(json.dumps({"hookSpecificOutput": {"hookEventName": "PostToolUse", "additionalContext": text}},
                             ensure_ascii=False))
    except Exception as e:  # never block Claude Code
        try:
            with open(_home() / "hook-errors.log", "a", encoding="utf-8") as f:
                f.write(f"post-tool: {type(e).__name__}: {e}\n")
        except Exception:
            pass
    return 0
