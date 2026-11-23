"""Providers: systems NEXUS points to instead of copying them.

- Projects: discovered from config roots, Claude Code's project list and Cortex's index list.
  Each gets a `project:<name>` card saying where it is, what has indexed it, whether that
  index is stale, and how to query it (Cortex for code, Graphify for its graph).
- CLAUDE.md files of those projects: `knowledge` pointers (ref only, short summary).
- Claude Code auto-memory files (~/.claude/projects/*/memory/*.md): `knowledge` pointers.

Code itself is never indexed here: Cortex and Graphify do that better.
"""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from pathlib import Path

from . import capabilities, experiences
from .capabilities import frontmatter
from .config import Config
from .store import Store

SOURCE_PROJECTS = "provider:projects"
SOURCE_MEMORY = "provider:cc-memory"
MARKERS = (".git", "pyproject.toml", "package.json", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
           "CLAUDE.md", "graphify-out")


def git_head(root: Path) -> str | None:
    g = root / ".git"
    try:
        if g.is_file():  # worktree / submodule: "gitdir: <path>"
            g = (root / g.read_text(encoding="utf-8").split(":", 1)[1].strip()).resolve()
        head = (g / "HEAD").read_text(encoding="utf-8").strip()
        if not head.startswith("ref: "):
            return head
        ref = head[5:]
        if (g / ref).exists():
            return (g / ref).read_text(encoding="utf-8").strip()
        for line in (g / "packed-refs").read_text(encoding="utf-8").splitlines():
            if line.endswith(" " + ref):
                return line.split()[0]
    except (OSError, IndexError):
        pass
    return None


def _run(args: list[str]) -> str:
    try:
        r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def cortex_projects() -> list[dict]:
    """Projects indexed by Cortex (read-only: `cortex list` + `cortex stats`)."""
    exe = shutil.which("cortex")
    if not exe:
        return []
    out = []
    for m in re.finditer(r"^\s*-\s+(.+?)\s+(\d+) files, (\d+) symbols", _run([exe, "list"]), re.M):
        stats = _run([exe, "stats", m.group(1)])
        root = re.search(r"^Root\s*:\s*(.+)$", stats, re.M)
        langs = re.search(r"^Languages:\s*(.+)$", stats, re.M)
        out.append({"name": m.group(1), "files": int(m.group(2)), "symbols": int(m.group(3)),
                    "root": root.group(1).strip() if root else None,
                    "languages": re.findall(r"([a-z+#]+)\(\d+\)", langs.group(1)) if langs else []})
    return out


def graphify_info(root: Path, store: Store) -> dict | None:
    g = root / "graphify-out" / "graph.json"
    if not g.exists():
        return None
    key = f"graphify:{g}"
    mtime = str(g.stat().st_mtime_ns)
    cached = store.kv_get(key)
    if cached and json.loads(cached)["mtime"] == mtime:
        info = json.loads(cached)
    else:  # graph.json can be large: parse once per change
        try:
            data = json.loads(g.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return None
        sizes: dict[str, int] = {}
        for n in data.get("nodes", []):
            c = n.get("community_name")
            if c:
                sizes[c] = sizes.get(c, 0) + 1
        info = {"mtime": mtime, "graph": str(g), "nodes": len(data.get("nodes", [])),
                "edges": len(data.get("links", data.get("edges", []))),
                "communities": [c for c, _ in sorted(sizes.items(), key=lambda kv: -kv[1])][:15],
                "built_at_commit": data.get("built_at_commit")}
        store.kv_set(key, json.dumps(info, ensure_ascii=False))
    head = git_head(root)
    built = info.get("built_at_commit")
    info["stale"] = bool(built and head and head != built)
    info["head"] = head
    return info


def candidate_roots(cfg: Config, cortex: list[dict]) -> list[Path]:
    roots = [Path(p) for p in cfg.project_roots] + [Path(c["root"]) for c in cortex if c["root"]]
    try:
        cc = json.loads(cfg.claude_json.read_text(encoding="utf-8")).get("projects", {}) or {}
    except (OSError, ValueError):
        cc = {}
    home = Path.home().resolve()
    for p in map(Path, cc):
        # shortcut: skip the home dir and Claude desktop scratch workspaces by path; make configurable if users need them.
        if not p.is_dir() or p.resolve() == home or "scratch-workspaces" in p.as_posix():
            continue
        roots.append(p)
        roots += [c for c in sorted(p.iterdir()) if c.is_dir() and not c.name.startswith(".")]
    seen, out = set(), []
    for r in roots:
        key = str(r.resolve()).lower()
        if key not in seen and r.is_dir() and any((r / m).exists() for m in MARKERS):
            seen.add(key)
            out.append(r)
    return out


def _excerpt(text: str, limit: int = 300) -> str:
    lines = [l.strip().lstrip("#").strip() for l in text.splitlines()]
    return " ".join(l for l in lines if l)[:limit]


def discover_projects(cfg: Config, store: Store) -> tuple[list[dict], list[tuple]]:
    cortex = cortex_projects()
    by_root = {str(Path(c["root"]).resolve()).lower(): c for c in cortex if c["root"]}
    nodes, edges = [], []
    for root in candidate_roots(cfg, cortex):
        cx = by_root.get(str(root.resolve()).lower())
        name = cx["name"] if cx else root.name
        pid = f"project:{name}"
        facts, tags, providers = [f"Project at {root}."], ["project"], {}
        if cx:
            providers["cortex"] = {k: cx[k] for k in ("name", "files", "symbols", "languages")}
            facts.append(f"Cortex index: {cx['files']} files, {cx['symbols']} symbols ({', '.join(cx['languages'][:4])}). "
                         f"For code questions use cortex_pack/cortex_ask with project '{name}'.")
            tags += cx["languages"]
        gi = graphify_info(root, store)
        if gi:
            providers["graphify"] = gi
            stale = f" STALE: built at {gi['built_at_commit'][:8]}, HEAD is {gi['head'][:8]}; run `graphify update .`." \
                if gi["stale"] else ""
            facts.append(f"Graphify graph: {gi['nodes']} nodes, {len(gi['communities'])}+ communities.{stale} "
                         f"Query with `graphify query \"<question>\" --graph \"{gi['graph']}\"`.")
            tags += gi["communities"]
        cm = root / "CLAUDE.md"
        if cm.exists():
            kid = f"knowledge:claude-md:{name}"
            nodes.append({"id": kid, "kind": "knowledge", "title": f"{name}: CLAUDE.md",
                          "summary": _excerpt(cm.read_text(encoding="utf-8", errors="replace")), "ref": str(cm),
                          "project": name, "tags": "claude-md instructions", "confidence": 0.8})
            edges.append((kid, pid, "belongs_to"))
            facts.append("Has CLAUDE.md.")
        if not providers:
            facts.append("Not indexed by Cortex or Graphify.")
        nodes.append({"id": pid, "kind": "project", "title": name, "summary": " ".join(facts), "ref": str(root),
                      "project": name, "tags": " ".join(tags), "confidence": 0.9,
                      "meta": {"root": str(root), "providers": providers, "git_head": git_head(root)}})
    return nodes, edges


def discover_cc_memory(cfg: Config) -> list[dict]:
    out = []
    for f in sorted((cfg.claude_dir / "projects").glob("*/memory/*.md")):
        if f.name == "MEMORY.md":
            continue
        fm, body = frontmatter(f)
        mtype = (fm.get("metadata") or {}).get("type") if isinstance(fm.get("metadata"), dict) else fm.get("type")
        out.append({"id": f"knowledge:cc-memory:{f.parent.parent.name}/{f.stem}", "kind": "knowledge",
                    "title": str(fm.get("name") or f.stem), "summary": str(fm.get("description") or _excerpt(body)),
                    "ref": str(f), "tags": f"claude-code-memory {mtype or ''}".strip(), "confidence": 0.8,
                    "meta": {"memory_type": mtype}})
    return out


def sync(store: Store, cfg: Config) -> dict:
    nodes, edges = discover_projects(cfg, store)
    proj = store.reconcile(nodes, SOURCE_PROJECTS, edges, op="provider")
    mem = store.reconcile(discover_cc_memory(cfg), SOURCE_MEMORY, op="provider")
    store.log("sync.providers", projects=len(nodes), new=proj["created"] + mem["created"],
              missing=proj["missing"] + mem["missing"])
    return {"projects": proj, "cc_memory": mem}


def sync_all(store: Store, cfg: Config, extra_roots: list[str] = ()) -> dict:
    """Everything a session start or `nexus sync` needs, incremental."""
    caps = capabilities.sync(store, cfg.claude_dir, cfg.claude_json, list(cfg.project_roots) + list(extra_roots),
                             cfg.redundancy_threshold)
    prov = sync(store, cfg)
    ver = experiences.verify_all(store)
    return {"capabilities": caps, **prov, "stale": ver["stale"]}


def project_card(store: Store, ref: str) -> dict | None:
    """What NEXUS knows about a project (by name or by a path inside it): providers, and every
    remembered entry with its validity. Stale entries list the changed files, so only those parts
    need re-analysis."""
    p = store.get(f"project:{ref}")
    if p is None:
        target = str(Path(ref).resolve()).lower() if ref else ""
        for n in store.nodes(kind="project"):
            root = str(n["meta"].get("root") or "").lower()
            if root and (target == root or target.startswith(root.rstrip("\\/") + ("\\" if "\\" in root else "/"))):
                p = n
                break
    if p is None:
        return None
    entries = {"active": [], "stale": []}
    for n in store.db.execute("SELECT id FROM nodes WHERE project=? AND kind!='project' AND source!=?", (p["title"], SOURCE_PROJECTS)).fetchall():
        e = store.get(n["id"])
        if e["fingerprint"]:
            v = experiences.verify(store, e["id"])
            e = {**store.get(e["id"]), "changed": v["changed"]}
        if e["status"] in entries:
            entries[e["status"]].append({"id": e["id"], "kind": e["kind"], "title": e["title"],
                                         "summary": e["summary"][:200], "changed": e.get("changed", [])})
    changed = sorted({f for e in entries["stale"] for f in e["changed"]})
    advice = ("No remembered understanding yet: analyse the project, then save it with nexus_remember "
              "(one entry per module/aspect, with its files) so later sessions can reuse it."
              if not entries["active"] and not entries["stale"] else
              f"Reuse the {len(entries['active'])} valid entries. Re-check only the stale ones "
              f"({len(changed)} changed files), then nexus_revalidate or update them." if entries["stale"] else
              f"All {len(entries['active'])} remembered entries are still valid: no re-analysis needed.")
    return {"project": {k: p[k] for k in ("id", "title", "summary", "ref")}, "providers": p["meta"].get("providers", {}),
            "entries": entries, "changed_files": changed, "advice": advice}
