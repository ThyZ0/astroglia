"""Capability engine: discovers what the agent can do in a Claude Code install.

Sources (read-only):
  ~/.claude/settings.json            enabledPlugins, hooks
  ~/.claude/plugins/installed_plugins.json   plugin install paths
  <plugin>/.claude-plugin/plugin.json, skills/*/SKILL.md, commands/*.md, agents/*.md, .mcp.json, hooks/hooks.json
  ~/.claude/skills/**/SKILL.md, ~/.claude/agents/*.md, ~/.claude/commands/*.md
  ~/.claude.json                     mcpServers (user + per-project)
  <project>/.mcp.json, <project>/.claude/{skills,agents,commands}

Nothing is executed. MCP env values are never stored (only their key names).
"""
from __future__ import annotations

import json
import re
from pathlib import Path

import yaml

from .store import Store, now
from .text import terms

CAP_KINDS = ("plugin", "skill", "command", "agent", "mcp_server", "hook")
SOURCE = "scan:claude-code"


def _read_json(p: Path) -> dict:
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def frontmatter(p: Path) -> tuple[dict, str]:
    """Return (frontmatter dict, body) of a Markdown file; tolerant of malformed YAML."""
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}, ""
    m = re.match(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", text, re.S)
    if not m:
        return {}, text
    try:
        fm = yaml.safe_load(m.group(1)) or {}
    except yaml.YAMLError:
        fm = {}
    return (fm if isinstance(fm, dict) else {}), m.group(2)


def _first_line(body: str) -> str:
    for line in body.splitlines():
        line = line.strip().lstrip("#").strip()
        if line:
            return line[:300]
    return ""


def _cap(kind, cid, title, summary, ref, origin, **meta) -> dict:
    return {"id": f"{kind}:{origin}" if cid == origin else f"{kind}:{origin}:{cid}", "kind": kind, "title": title, "summary": (summary or "").strip(),
            "ref": str(ref) if ref else None, "source": SOURCE, "tags": f"{kind} {origin}",
            "confidence": 0.9, "status": "active", "meta": {"origin": origin, **meta}}


def _md_entries(folder: Path, kind: str, origin: str, pattern: str) -> list[dict]:
    out = []
    if not folder.is_dir():
        return out
    for f in sorted(folder.glob(pattern)):
        if any(part.startswith(".") for part in f.relative_to(folder).parts):
            continue  # hidden sync buckets / caches
        fm, body = frontmatter(f)
        name = str(fm.get("name") or (f.parent.name if f.name == "SKILL.md" else f.stem))
        desc = fm.get("description") or _first_line(body)
        meta = {k: fm[k] for k in ("allowed-tools", "tools", "model", "argument-hint", "compatibility") if k in fm}
        out.append(_cap(kind, name, name, str(desc), f, origin, **meta))
    return out


# What well-known services do, keyed by a fragment of the server name. Product knowledge, not guesses:
# an unknown name simply gets no description.
KNOWN_SERVICES = {
    "gmail": "Email: read, search, draft and send mail in Gmail",
    "outlook": "Email and calendar in Microsoft Outlook",
    "calendar": "Calendar: list, create and update events and meetings",
    "slack": "Team chat: read and post messages in Slack channels",
    "discord": "Chat: messages in Discord channels",
    "teams": "Team chat and meetings in Microsoft Teams",
    "linear": "Issue tracker: create and update issues and tickets in Linear",
    "jira": "Issue tracker: Jira issues, tickets and sprints",
    "atlassian": "Issue tracker and wiki: Jira tickets and Confluence pages",
    "asana": "Project and task tracker: Asana tasks and projects",
    "clickup": "Project and task tracker: ClickUp tasks",
    "monday": "Project and task tracker: monday.com boards and items",
    "trello": "Task boards: Trello cards and lists",
    "notion": "Notes, docs and wiki pages in Notion",
    "github": "GitHub: repositories, pull requests, issues and code review",
    "gitlab": "GitLab: repositories, merge requests and issues",
    "drive": "Files and documents in Google Drive",
    "figma": "Design files in Figma",
    "postgres": "Database: query a PostgreSQL database",
    "sqlite": "Database: query a SQLite database",
    "playwright": "Browser automation: drive a real browser, fill forms, test web pages",
    "puppeteer": "Browser automation: drive a real browser",
    "sentry": "Error monitoring: Sentry issues and stack traces",
    "stripe": "Payments: Stripe customers, charges and invoices",
}


def describe_service(name: str) -> str | None:
    n = name.lower()
    return next((d for key, d in KNOWN_SERVICES.items() if key in n), None)


def _mcp_entries(servers: dict, origin: str, project: str | None = None) -> list[dict]:
    out = []
    for name, spec in (servers or {}).items():
        if not isinstance(spec, dict):
            continue
        transport = spec.get("type") or ("http" if spec.get("url") else "stdio")
        target = spec.get("url") or " ".join([spec.get("command", ""), *map(str, spec.get("args", []))]).strip()
        known = describe_service(name)
        c = _cap("mcp_server", name, name, (f"{known}. " if known else "") + f"MCP server ({transport}): {target}", None, origin,
                 transport=transport, target=target, env_keys=sorted((spec.get("env") or {}).keys()))
        if project:
            c["project"] = project
            c["id"] += f"@{project}"
        out.append(c)
    return out


def _hook_entries(hooks: dict, origin: str, ref: Path) -> list[dict]:
    out = []
    for event, groups in (hooks or {}).items():
        for gi, group in enumerate(groups or []):
            for hi, h in enumerate(group.get("hooks", []) if isinstance(group, dict) else []):
                cmd = h.get("command") or h.get("prompt") or h.get("type", "")
                out.append(_cap("hook", f"{event}#{gi}.{hi}", f"{event} hook ({origin})",
                                f"Runs on {event} (matcher {group.get('matcher', '*')}): {cmd[:200]}", ref, origin,
                                event=event, matcher=group.get("matcher")))
    return out


def discover(claude_dir: Path, claude_json: Path, project_roots: list[str] = ()) -> tuple[list[dict], list[tuple]]:
    """Return (capability nodes, edges[(src, dst, type)]). Pure read of the filesystem."""
    caps: list[dict] = []
    edges: list[tuple] = []
    settings = _read_json(claude_dir / "settings.json")
    enabled = settings.get("enabledPlugins", {}) or {}
    installed = _read_json(claude_dir / "plugins" / "installed_plugins.json").get("plugins", {}) or {}

    plugin_roots = [(key, Path(inst[0].get("installPath", "")), bool(enabled.get(key, False)))
                    for key, inst in installed.items() if inst]
    # Plugins synced from a claude.ai account: plugins/synced/<bucket>/<uuid>/.claude-plugin/plugin.json (always on).
    synced = claude_dir / "plugins" / "synced"
    for mf in sorted(synced.glob("*/*/.claude-plugin/plugin.json")) if synced.is_dir() else []:
        root = mf.parent.parent
        if root.parent.name.startswith("."):
            continue
        name = _read_json(mf).get("name") or root.name
        plugin_roots.append((f"{name}@synced", root, True))

    for key, root, is_enabled in plugin_roots:
        manifest = _read_json(root / ".claude-plugin" / "plugin.json")
        plugin = _cap("plugin", key, manifest.get("name", key), manifest.get("description", ""), root, key,
                      version=manifest.get("version"), enabled=is_enabled)
        if not is_enabled:
            plugin["status"] = "disabled"
        caps.append(plugin)
        children = (_md_entries(root / "skills", "skill", key, "*/SKILL.md")
                    + _md_entries(root / "commands", "command", key, "*.md")
                    + _md_entries(root / "agents", "agent", key, "*.md")
                    + _mcp_entries(_read_json(root / ".mcp.json").get("mcpServers") or _read_json(root / ".mcp.json"), key)
                    + _mcp_entries(manifest.get("mcpServers") if isinstance(manifest.get("mcpServers"), dict) else {}, key))
        hook_files = [root / "hooks" / "hooks.json"]
        hk = manifest.get("hooks")
        for rel in ([hk] if isinstance(hk, str) else hk if isinstance(hk, list) else []):
            hook_files.append((root / rel).resolve())
        for hf in dict.fromkeys(hook_files):
            children += _hook_entries(_read_json(hf).get("hooks", {}), key, hf)
        for c in children:
            if not is_enabled:
                c["status"] = "disabled"
            edges.append((c["id"], plugin["id"], "belongs_to"))
        caps += children

    caps += _md_entries(claude_dir / "skills", "skill", "user", "**/SKILL.md")
    caps += _md_entries(claude_dir / "commands", "command", "user", "*.md")
    caps += _md_entries(claude_dir / "agents", "agent", "user", "*.md")
    caps += _hook_entries(settings.get("hooks", {}), "user", claude_dir / "settings.json")

    cj = _read_json(claude_json)
    caps += _mcp_entries(cj.get("mcpServers", {}), "user")
    for proj, pdata in (cj.get("projects") or {}).items():
        if isinstance(pdata, dict) and pdata.get("mcpServers"):
            caps += _mcp_entries(pdata["mcpServers"], "local", project=proj)

    for pr in project_roots:
        p = Path(pr)
        caps += _mcp_entries(_read_json(p / ".mcp.json").get("mcpServers", {}), "project", project=str(p))
        for sub, kind, pat in (("skills", "skill", "*/SKILL.md"), ("commands", "command", "*.md"), ("agents", "agent", "*.md")):
            for c in _md_entries(p / ".claude" / sub, kind, "project", pat):
                c["project"], c["id"] = str(p), c["id"] + f"@{p.name}"
                caps.append(c)

    # De-duplicate ids (same skill visible through two paths): keep first.
    seen, unique = set(), []
    for c in caps:
        if c["id"] not in seen:
            seen.add(c["id"]); unique.append(c)
    return unique, edges


def similarity(a: str, b: str) -> float:
    ta, tb = set(terms(a)), set(terms(b))
    if len(ta) < 3 or len(tb) < 3:
        return 0.0
    return len(ta & tb) / len(ta | tb)


def sync(store: Store, claude_dir: Path, claude_json: Path, project_roots: list[str] = (),
         redundancy_threshold: float = 0.35) -> dict:
    """Incremental: upsert what changed, flag vanished capabilities as 'missing' (never delete)."""
    caps, edges = discover(claude_dir, claude_json, project_roots)
    from .probe import _signature
    for c in caps:  # keep what `astroglia probe` learned while the server's command line is unchanged
        old = store.get(c["id"]) if c["kind"] == "mcp_server" else None
        pr = old and old["meta"].get("probe")
        if pr and pr.get("count") is not None and pr.get("signature") == _signature(c["meta"]):
            c["summary"] = c["summary"] + " Tools (" + old["summary"].split(" Tools (", 1)[1] if " Tools (" in old["summary"] else c["summary"]
            c["body"], c["meta"]["probe"] = old["body"], pr
        elif pr and pr.get("signature") == _signature(c["meta"]):
            c["meta"]["probe"] = pr  # remember failures too, so they are not retried until the server changes
    report = store.reconcile(caps, SOURCE, edges, op="scan")

    # Redundancy: lexical overlap of descriptions between capabilities that do "work"
    # (skills, commands, agents). shortcut: Jaccard on terms, upgrade to embeddings when the bench shows misses.
    if report["created"] or report["updated"]:
        work = [c for c in caps if c["kind"] in ("skill", "command", "agent")]
        store.db.execute("DELETE FROM edges WHERE type='similar_to' AND source='auto:lexical'")
        for i, a in enumerate(work):
            for b in work[i + 1:]:
                s = similarity(a["title"] + " " + a["summary"], b["title"] + " " + b["summary"])
                if s >= redundancy_threshold:
                    store.link(a["id"], b["id"], "similar_to", source="auto:lexical", confidence=round(s, 3))
        # Explicit mentions: descriptions often name their neighbours ("not for X (use Y)").
        # shortcut: only distinctive names (hyphenated or >= 8 chars) to avoid matching common words like "docs".
        store.db.execute("DELETE FROM edges WHERE type='related_to' AND source='auto:mention'")
        for a in work:
            text = " " + a["summary"].lower() + " "
            for b in work:
                name = b["title"].lower()
                if b is a or name == a["title"].lower() or not ("-" in name or len(name) >= 8):
                    continue
                if re.search(rf"(?<![\w-]){re.escape(name)}(?![\w-])", text):
                    store.link(a["id"], b["id"], "related_to", source="auto:mention", confidence=0.9)
    store.kv_set("last_capability_sync", now())
    store.log("sync.capabilities", created=len(report["created"]), updated=len(report["updated"]),
              missing=len(report["missing"]), new_ids=report["created"][:50])
    return report
