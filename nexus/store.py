"""SQLite store: nodes, typed edges, FTS5 index, version history, event log.

Every mutation of a node snapshots the previous version into `history`,
so any change (manual or automatic) can be inspected and reverted.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS nodes(
  id TEXT PRIMARY KEY,
  kind TEXT NOT NULL,
  title TEXT NOT NULL,
  summary TEXT NOT NULL DEFAULT '',
  body TEXT,
  ref TEXT,
  source TEXT NOT NULL,
  project TEXT,
  tags TEXT NOT NULL DEFAULT '',
  confidence REAL NOT NULL DEFAULT 0.7,
  importance REAL NOT NULL DEFAULT 0.5,
  status TEXT NOT NULL DEFAULT 'active',
  created TEXT NOT NULL,
  updated TEXT NOT NULL,
  verified TEXT NOT NULL,
  fingerprint TEXT,
  meta TEXT NOT NULL DEFAULT '{}',
  uses INTEGER NOT NULL DEFAULT 0,
  successes INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS nodes_kind ON nodes(kind);
CREATE INDEX IF NOT EXISTS nodes_project ON nodes(project);
CREATE TABLE IF NOT EXISTS edges(
  src TEXT NOT NULL, dst TEXT NOT NULL, type TEXT NOT NULL,
  source TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 0.7,
  created TEXT NOT NULL, verified TEXT NOT NULL,
  PRIMARY KEY(src, dst, type)
);
CREATE INDEX IF NOT EXISTS edges_dst ON edges(dst);
CREATE VIRTUAL TABLE IF NOT EXISTS nodes_fts USING fts5(
  id UNINDEXED, title, summary, tags, body,
  tokenize='porter unicode61 remove_diacritics 2'
);
CREATE TABLE IF NOT EXISTS history(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  node_id TEXT NOT NULL, ts TEXT NOT NULL, op TEXT NOT NULL, snapshot TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS history_node ON history(node_id);
CREATE TABLE IF NOT EXISTS events(
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  ts TEXT NOT NULL, kind TEXT NOT NULL, payload TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS kv(key TEXT PRIMARY KEY, value TEXT NOT NULL);
"""

# Fields that define a node's content; a change to any of them creates a history entry.
_CONTENT = ("kind", "title", "summary", "body", "ref", "source", "project", "tags",
            "confidence", "importance", "status", "fingerprint", "meta")

EDGE_TYPES = {"belongs_to", "depends_on", "related_to", "complements", "replaces",
              "similar_to", "used_in", "derived_from", "referenced_by", "incompatible_with"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class Store:
    def __init__(self, path: str | Path):
        self.path = Path(path)
        if str(path) != ":memory:":
            self.path.parent.mkdir(parents=True, exist_ok=True)
        self.db = sqlite3.connect(str(path), timeout=5)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self._migrate()

    def _migrate(self) -> None:
        v = self.db.execute("PRAGMA user_version").fetchone()[0]
        if v > SCHEMA_VERSION:
            raise RuntimeError(f"Database schema v{v} is newer than this NEXUS (v{SCHEMA_VERSION}); upgrade NEXUS.")
        if v < 1:
            self.db.executescript(_SCHEMA)
        # future migrations: `if v < 2: ...`
        self.db.execute(f"PRAGMA user_version={SCHEMA_VERSION}")
        self.db.commit()

    def close(self) -> None:
        self.db.close()

    # ---------- nodes ----------
    def get(self, node_id: str) -> dict | None:
        r = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        return _row(r) if r else None

    def upsert(self, node: dict, op: str = "upsert") -> str:
        """Insert or update a node. Returns 'created', 'updated' or 'unchanged'."""
        node = dict(node)
        if isinstance(node.get("meta"), dict):
            node["meta"] = json.dumps(node["meta"], sort_keys=True, ensure_ascii=False)
        if isinstance(node.get("fingerprint"), dict):
            node["fingerprint"] = json.dumps(node["fingerprint"], sort_keys=True)
        old = self.db.execute("SELECT * FROM nodes WHERE id=?", (node["id"],)).fetchone()
        ts = now()
        if old is None:
            node.setdefault("created", ts)
            node.setdefault("verified", ts)
            node["updated"] = ts
            cols = ", ".join(node)
            self.db.execute(f"INSERT INTO nodes({cols}) VALUES({', '.join('?' * len(node))})", tuple(node.values()))
            self._index(node["id"])
            self.db.commit()
            return "created"
        merged = {k: old[k] for k in old.keys()}
        changed = any(k in node and node[k] != merged[k] for k in _CONTENT)
        if not changed:
            if "verified" in node:
                self.db.execute("UPDATE nodes SET verified=? WHERE id=?", (node["verified"], node["id"]))
                self.db.commit()
            return "unchanged"
        self.db.execute("INSERT INTO history(node_id, ts, op, snapshot) VALUES(?,?,?,?)",
                        (node["id"], ts, op, json.dumps(merged, ensure_ascii=False)))
        merged.update(node)
        merged["updated"] = ts
        merged.setdefault("verified", ts)
        sets = ", ".join(f"{k}=?" for k in merged if k != "id")
        self.db.execute(f"UPDATE nodes SET {sets} WHERE id=?",
                        tuple(v for k, v in merged.items() if k != "id") + (node["id"],))
        self._index(node["id"])
        self.db.commit()
        return "updated"

    def set_status(self, node_id: str, status: str, op: str, **meta_updates) -> None:
        n = self.get(node_id)
        if n is None:
            return
        meta = n["meta"]
        meta.update(meta_updates)
        self.upsert({"id": node_id, "status": status, "meta": meta}, op=op)

    def delete(self, node_id: str) -> bool:
        n = self.db.execute("SELECT * FROM nodes WHERE id=?", (node_id,)).fetchone()
        if n is None:
            return False
        self.db.execute("INSERT INTO history(node_id, ts, op, snapshot) VALUES(?,?,?,?)",
                        (node_id, now(), "delete", json.dumps({k: n[k] for k in n.keys()}, ensure_ascii=False)))
        self.db.execute("DELETE FROM nodes WHERE id=?", (node_id,))
        self.db.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
        self.db.execute("DELETE FROM edges WHERE src=? OR dst=?", (node_id, node_id))
        self.db.commit()
        return True

    def history(self, node_id: str) -> list[dict]:
        rows = self.db.execute("SELECT id, ts, op, snapshot FROM history WHERE node_id=? ORDER BY id DESC", (node_id,))
        return [{"history_id": r["id"], "ts": r["ts"], "op": r["op"], "snapshot": json.loads(r["snapshot"])} for r in rows]

    def restore(self, history_id: int) -> str:
        r = self.db.execute("SELECT node_id, snapshot FROM history WHERE id=?", (history_id,)).fetchone()
        if r is None:
            raise KeyError(f"no history entry {history_id}")
        snap = json.loads(r["snapshot"])
        for k in ("created", "updated", "uses", "successes"):
            snap.pop(k, None)
        return self.upsert(snap, op=f"restore:{history_id}")

    def _index(self, node_id: str) -> None:
        r = self.db.execute("SELECT title, summary, tags, body FROM nodes WHERE id=?", (node_id,)).fetchone()
        self.db.execute("DELETE FROM nodes_fts WHERE id=?", (node_id,))
        self.db.execute("INSERT INTO nodes_fts(id, title, summary, tags, body) VALUES(?,?,?,?,?)",
                        (node_id, r["title"], r["summary"], r["tags"], r["body"] or ""))

    def nodes(self, kind: str | None = None, status: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM nodes WHERE 1=1", []
        if kind:
            q += " AND kind=?"; args.append(kind)
        if status:
            q += " AND status=?"; args.append(status)
        return [_row(r) for r in self.db.execute(q + " ORDER BY kind, title", args)]

    def bump(self, node_id: str, uses: int = 0, successes: int = 0) -> None:
        self.db.execute("UPDATE nodes SET uses=uses+?, successes=successes+? WHERE id=?", (uses, successes, node_id))
        self.db.commit()

    def reconcile(self, nodes: list[dict], source: str, edges: list[tuple] = (), op: str = "sync") -> dict:
        """Make the store match what a source currently reports: upsert, and flag vanished nodes
        of that source as 'missing' (never delete). Returns created/updated/missing ids."""
        ts = now()
        report = {"created": [], "updated": [], "missing": [], "unchanged": 0}
        for n in nodes:
            r = self.upsert({**n, "source": source, "verified": ts}, op=op)
            if r == "unchanged":
                report["unchanged"] += 1
            else:
                report[r].append(n["id"])
        found = {n["id"] for n in nodes}
        for row in self.db.execute("SELECT id FROM nodes WHERE source=? AND status!='missing'", (source,)).fetchall():
            if row["id"] not in found:
                self.set_status(row["id"], "missing", op=op, missing_since=ts)
                report["missing"].append(row["id"])
        for src, dst, t in edges:
            self.link(src, dst, t, source=source, confidence=1.0)
        return report

    # ---------- edges ----------
    def link(self, src: str, dst: str, type: str, source: str, confidence: float = 0.7) -> None:
        if type not in EDGE_TYPES:
            raise ValueError(f"unknown edge type {type!r}; expected one of {sorted(EDGE_TYPES)}")
        ts = now()
        self.db.execute(
            "INSERT INTO edges(src,dst,type,source,confidence,created,verified) VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(src,dst,type) DO UPDATE SET confidence=excluded.confidence, verified=excluded.verified, source=excluded.source",
            (src, dst, type, source, confidence, ts, ts))
        self.db.commit()

    def unlink(self, src: str, dst: str, type: str) -> None:
        self.db.execute("DELETE FROM edges WHERE src=? AND dst=? AND type=?", (src, dst, type))
        self.db.commit()

    def edges(self, node_id: str | None = None, type: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM edges WHERE 1=1", []
        if node_id:
            q += " AND (src=? OR dst=?)"; args += [node_id, node_id]
        if type:
            q += " AND type=?"; args.append(type)
        return [dict(r) for r in self.db.execute(q, args)]

    # ---------- search ----------
    def fts(self, match: str, limit: int = 60) -> list[tuple[str, float]]:
        # bm25 column weights: id, title, summary, tags, body
        rows = self.db.execute(
            "SELECT id, bm25(nodes_fts, 0, 6.0, 2.0, 3.0, 1.0) AS s FROM nodes_fts WHERE nodes_fts MATCH ? ORDER BY s LIMIT ?",
            (match, limit))
        return [(r["id"], r["s"]) for r in rows]

    # ---------- events / kv ----------
    def log(self, kind: str, /, **payload) -> int:
        cur = self.db.execute("INSERT INTO events(ts, kind, payload) VALUES(?,?,?)",
                              (now(), kind, json.dumps(payload, ensure_ascii=False)))
        self.db.commit()
        return cur.lastrowid

    def events(self, limit: int = 50, kind: str | None = None) -> list[dict]:
        q, args = "SELECT * FROM events", []
        if kind:
            q += " WHERE kind=?"; args.append(kind)
        rows = self.db.execute(q + " ORDER BY id DESC LIMIT ?", args + [limit])
        return [{"id": r["id"], "ts": r["ts"], "kind": r["kind"], "payload": json.loads(r["payload"])} for r in rows]

    def kv_get(self, key: str, default: str | None = None) -> str | None:
        r = self.db.execute("SELECT value FROM kv WHERE key=?", (key,)).fetchone()
        return r["value"] if r else default

    def kv_set(self, key: str, value: str) -> None:
        self.db.execute("INSERT INTO kv(key,value) VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (key, value))
        self.db.commit()

    def stats(self) -> dict:
        kinds = {r[0]: r[1] for r in self.db.execute("SELECT kind, COUNT(*) FROM nodes GROUP BY kind")}
        status = {r[0]: r[1] for r in self.db.execute("SELECT status, COUNT(*) FROM nodes GROUP BY status")}
        edges = {r[0]: r[1] for r in self.db.execute("SELECT type, COUNT(*) FROM edges GROUP BY type")}
        return {"nodes_by_kind": kinds, "nodes_by_status": status, "edges_by_type": edges,
                "events": self.db.execute("SELECT COUNT(*) FROM events").fetchone()[0]}

    def backup(self, dest: str | Path) -> Path:
        dest = Path(dest)
        dest.parent.mkdir(parents=True, exist_ok=True)
        out = sqlite3.connect(str(dest))
        with out:
            self.db.backup(out)
        out.close()
        return dest


def _row(r: sqlite3.Row) -> dict:
    d = {k: r[k] for k in r.keys()}
    d["meta"] = json.loads(d["meta"] or "{}")
    d["fingerprint"] = json.loads(d["fingerprint"]) if d.get("fingerprint") else None
    return d
