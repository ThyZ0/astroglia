"""`astroglia` command line."""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

from . import __version__, capabilities, config, experiences, providers, router
from .store import Store

HOOK_MARK = "-m astroglia hook"


def _out(obj) -> None:
    sys.stdout.reconfigure(encoding="utf-8")
    print(json.dumps(obj, indent=2, ensure_ascii=False) if not isinstance(obj, str) else obj)


def _hook_cmd(event: str) -> str:
    return f'"{Path(sys.executable).as_posix()}" -m astroglia hook {event}'


def _settings_plan(cfg: config.Config, with_prompt_hook: bool) -> tuple[Path, dict, dict]:
    path = cfg.claude_dir / "settings.json"
    cur = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    new = json.loads(json.dumps(cur))
    hooks = new.setdefault("hooks", {})
    wanted = {"SessionStart": ("session-start", 15), "Stop": ("stop", 10)}
    if with_prompt_hook:
        wanted["UserPromptSubmit"] = ("prompt", 5)
    for event, (arg, timeout) in wanted.items():
        groups = [g for g in hooks.get(event, []) if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        groups.append({"hooks": [{"type": "command", "command": _hook_cmd(arg), "timeout": timeout}]})
        hooks[event] = groups
    return path, cur, new


def _strip_hooks(settings: dict) -> dict:
    new = json.loads(json.dumps(settings))
    for event in list(new.get("hooks", {})):
        groups = [g for g in new["hooks"][event] if not any(HOOK_MARK in h.get("command", "") for h in g.get("hooks", []))]
        if groups:
            new["hooks"][event] = groups
        else:
            del new["hooks"][event]
    if new.get("hooks") == {}:
        del new["hooks"]
    return new


def cmd_install(cfg, a):
    path, cur, new = _settings_plan(cfg, a.prompt_hook)
    claude = shutil.which("claude")
    mcp_cmd = [claude or "claude", "mcp", "add", "--scope", "user", "astroglia", "--", sys.executable, "-m", "astroglia", "mcp"]
    plan = {"settings_file": str(path), "hooks_to_set": new.get("hooks"), "mcp_command": " ".join(mcp_cmd),
            "claude_cli_found": bool(claude)}
    if not a.yes:
        _out({"dry_run": True, **plan, "hint": "re-run with --yes to apply (settings.json is backed up first)"})
        return 0
    backup = cfg.home / "backups" / f"settings-{time.strftime('%Y%m%d-%H%M%S')}.json"
    backup.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, backup)
    path.write_text(json.dumps(new, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    mcp_ok = False
    if claude:
        subprocess.run([claude, "mcp", "remove", "--scope", "user", "astroglia"], capture_output=True)
        mcp_ok = subprocess.run(mcp_cmd, capture_output=True, text=True).returncode == 0
    _out({"installed": True, "settings_backup": str(backup) if path.exists() else None, "mcp_registered": mcp_ok,
          **({} if mcp_ok else {"manual_mcp": " ".join(mcp_cmd)})})
    return 0


def cmd_uninstall(cfg, a):
    path = cfg.claude_dir / "settings.json"
    if path.exists():
        cur = json.loads(path.read_text(encoding="utf-8"))
        stripped = _strip_hooks(cur)
        if stripped != cur:
            (cfg.home / "backups").mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, cfg.home / "backups" / f"settings-pre-uninstall-{time.strftime('%Y%m%d-%H%M%S')}.json")
            path.write_text(json.dumps(stripped, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    claude = shutil.which("claude")
    if claude:
        subprocess.run([claude, "mcp", "remove", "--scope", "user", "astroglia"], capture_output=True)
    msg = {"hooks_removed": True, "mcp_removed": bool(claude)}
    if a.purge:
        if not a.yes:
            _out({**msg, "purge": f"refused without --yes; would delete {cfg.home}"})
            return 1
        shutil.rmtree(cfg.home, ignore_errors=True)
        msg["purged"] = str(cfg.home)
    _out(msg)
    return 0


def cmd_doctor(cfg, a):
    checks = []
    def check(name, ok, detail=""):
        checks.append({"check": name, "ok": bool(ok), "detail": detail})
    check("python >= 3.11", sys.version_info >= (3, 11), sys.version.split()[0])
    check("claude dir", cfg.claude_dir.is_dir(), str(cfg.claude_dir))
    check("~/.claude.json", cfg.claude_json.exists(), str(cfg.claude_json))
    try:
        s = Store(cfg.db_path); s.fts('"x"'); s.close()
        check("database + FTS5", True, str(cfg.db_path))
    except Exception as e:
        check("database + FTS5", False, f"{type(e).__name__}: {e}")
    settings = cfg.claude_dir / "settings.json"
    hooked = settings.exists() and HOOK_MARK in settings.read_text(encoding="utf-8")
    check("SessionStart hook installed", hooked, "run `astroglia install --yes`" if not hooked else "")
    cj = json.loads(cfg.claude_json.read_text(encoding="utf-8")) if cfg.claude_json.exists() else {}
    check("MCP server registered", "astroglia" in (cj.get("mcpServers") or {}), "")
    for tool in ("claude", "cortex", "graphify"):
        check(f"{tool} on PATH (optional)", shutil.which(tool), shutil.which(tool) or "not found")
    errlog = cfg.home / "hook-errors.log"
    check("no hook errors", not errlog.exists(), str(errlog) if errlog.exists() else "")
    _out(checks)
    return 0 if all(c["ok"] for c in checks if "optional" not in c["check"] and "installed" not in c["check"]
                    and "registered" not in c["check"]) else 1


def main(argv=None) -> int:
    p = argparse.ArgumentParser(prog="astroglia", description="Astroglia: capability registry, experience memory and context router for Claude Code")
    p.add_argument("--version", action="version", version=__version__)
    p.add_argument("--home", help="data dir (default ~/.astroglia or $ASTROGLIA_HOME)")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("sync", help="scan capabilities and verify memories (incremental)")
    sub.add_parser("status", help="counts and recent events")
    sub.add_parser("doctor", help="diagnose installation")
    r = sub.add_parser("route", help="select resources for a task"); r.add_argument("task"); r.add_argument("--project")
    r.add_argument("--budget", type=int, default=1200); r.add_argument("--kind", action="append")
    s = sub.add_parser("search"); s.add_argument("query"); s.add_argument("--kind"); s.add_argument("--limit", type=int, default=10)
    g = sub.add_parser("show", help="full entry + history"); g.add_argument("id")
    pj = sub.add_parser("project", help="project card: providers + remembered entries and their validity")
    pj.add_argument("ref", nargs="?", default=".", help="project name or a path inside it (default: current dir)")
    m = sub.add_parser("remember", help="save an experience/decision/knowledge")
    m.add_argument("title"); m.add_argument("summary"); m.add_argument("--body", default="")
    m.add_argument("--kind", default="experience", choices=experiences.MEMORY_KINDS); m.add_argument("--project")
    m.add_argument("--tag", action="append", default=[]); m.add_argument("--file", action="append", default=[])
    c = sub.add_parser("capabilities", help="list capabilities"); c.add_argument("--kind"); c.add_argument("--all", action="store_true")
    c.add_argument("--redundant", action="store_true", help="show detected overlaps")
    d = sub.add_parser("forget", help="delete an entry (kept in history)"); d.add_argument("id")
    rs = sub.add_parser("restore-version", help="restore an entry from its history"); rs.add_argument("history_id", type=int)
    b = sub.add_parser("backup"); b.add_argument("--out")
    rb = sub.add_parser("restore", help="restore database from a backup file"); rb.add_argument("file"); rb.add_argument("--yes", action="store_true")
    bn = sub.add_parser("bench", help="routing benchmark vs plain BM25"); bn.add_argument("labels")
    ui = sub.add_parser("ui", help="open the local web interface"); ui.add_argument("--port", type=int, default=8765)
    ui.add_argument("--no-browser", action="store_true")
    sub.add_parser("mcp", help="run the MCP server (stdio)")
    h = sub.add_parser("hook", help="Claude Code hook entry point"); h.add_argument("event", choices=["session-start", "prompt", "stop"])
    i = sub.add_parser("install", help="register hooks + MCP in Claude Code"); i.add_argument("--yes", action="store_true")
    i.add_argument("--prompt-hook", action="store_true", help="also route every prompt (opt-in, costs context)")
    u = sub.add_parser("uninstall"); u.add_argument("--purge", action="store_true", help="also delete all Astroglia data"); u.add_argument("--yes", action="store_true")
    a = p.parse_args(argv)
    try:
        cfg = config.load(a.home)
    except (ValueError, OSError) as e:  # tomllib.TOMLDecodeError is a ValueError
        _out(f"error: cannot read Astroglia config.toml: {e}"); return 1

    if a.cmd == "hook":
        from . import hooks
        return hooks.run(a.event)
    if a.cmd == "ui":
        from . import web
        try:
            web.serve(cfg, a.port, not a.no_browser)
        except OSError as e:  # Windows reports a busy port as PermissionError (WinError 10013)
            _out(f"error: port {a.port} is already in use or not allowed ({e.strerror or e}). Try `astroglia ui --port 8766`."); return 1
        return 0
    if a.cmd == "mcp":
        from . import mcp_server
        mcp_server.main(); return 0
    if a.cmd in ("install", "uninstall", "doctor"):
        return {"install": cmd_install, "uninstall": cmd_uninstall, "doctor": cmd_doctor}[a.cmd](cfg, a)
    if a.cmd == "restore":
        f = Path(a.file)
        if not f.exists():
            _out(f"no such file: {f}"); return 1
        if not a.yes:
            _out(f"would replace {cfg.db_path} with {f} (current db is backed up first). Re-run with --yes."); return 1
        st = Store(cfg.db_path)
        safety = st.backup(cfg.home / "backups" / f"pre-restore-{time.strftime('%Y%m%d-%H%M%S')}.db"); st.close()
        src = Store(f); src.backup(cfg.db_path); src.close()
        _out({"restored_from": str(f), "previous_saved_to": str(safety)}); return 0

    st = Store(cfg.db_path)
    try:
        if a.cmd == "sync":
            rep = providers.sync_all(st, cfg)
            count = lambda r: {k: (v if isinstance(v, int) else len(v)) for k, v in r.items()}
            _out({"capabilities": count(rep["capabilities"]), "projects": count(rep["projects"]),
                  "cc_memory": count(rep["cc_memory"]), "briefs": count(rep["briefs"]),
                  "new": (rep["capabilities"]["created"] + rep["projects"]["created"] + rep["cc_memory"]["created"])[:40],
                  "missing": rep["capabilities"]["missing"] + rep["projects"]["missing"] + rep["cc_memory"]["missing"],
                  "stale": rep["stale"]})
        elif a.cmd == "status":
            _out({"db": str(cfg.db_path), "last_capability_sync": st.kv_get("last_capability_sync"), **st.stats(),
                  "recent": [{k: e[k] for k in ("ts", "kind")} for e in st.events(10)]})
        elif a.cmd == "route":
            _out(router.route(st, cfg, a.task, project=a.project, budget=a.budget, kinds=a.kind))
        elif a.cmd == "search":
            r = router.route(st, cfg, a.query, budget=10_000, kinds=[a.kind] if a.kind else None, limit=a.limit)
            _out([{k: s[k] for k in ("id", "score", "title")} for s in r["selected"]])
        elif a.cmd == "show":
            n = st.get(a.id)
            if n is None:
                _out(f"unknown id {a.id}"); return 1
            _out({"entry": n, "relations": st.edges(a.id), "history": st.history(a.id)[:10]})
        elif a.cmd == "project":
            card = providers.project_card(st, a.ref)
            if card is None:
                _out(f"unknown project {a.ref!r} (run `astroglia sync`; projects come from Claude Code, Cortex and config roots)"); return 1
            _out(card)
        elif a.cmd == "remember":
            _out(experiences.remember(st, a.title, a.summary, a.body, kind=a.kind, project=a.project, tags=a.tag,
                                      files=a.file, source="user"))
        elif a.cmd == "capabilities":
            if a.redundant:
                _out([f"{e['src']}  ~{e['confidence']:.2f}~  {e['dst']}" for e in
                      sorted(st.edges(type="similar_to"), key=lambda e: -e["confidence"])])
            else:
                rows = [n for n in st.nodes(kind=a.kind) if n["kind"] in capabilities.CAP_KINDS and (a.all or n["status"] == "active")]
                _out("\n".join(f"{n['status']:8} {n['id']:60} {n['summary'][:70]}" for n in rows) or "none (run `astroglia sync`)")
        elif a.cmd == "forget":
            _out({"deleted": st.delete(a.id)})
        elif a.cmd == "restore-version":
            _out({"result": st.restore(a.history_id)})
        elif a.cmd == "bench":
            from . import bench
            _out(bench.run(st, cfg, a.labels))
        elif a.cmd == "backup":
            out = Path(a.out) if a.out else cfg.home / "backups" / f"astroglia-{time.strftime('%Y%m%d-%H%M%S')}.db"
            _out({"backup": str(st.backup(out))})
    except (ValueError, KeyError) as e:
        _out(f"error: {e}"); return 1
    finally:
        st.close()
    return 0
