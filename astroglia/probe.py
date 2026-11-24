"""Learn what local MCP servers actually do by asking them for their tool list (MCP tools/list).

An MCP server's configuration holds only a command line, so routing had nothing to match "who calls this
function" against. Claude Code itself lists these tools at every session start; this does the same once and
keeps the result. Explicit only (`astroglia probe`): it starts programs the user configured.

- stdio servers only: remote (http/sse) servers need the network and the user's logins, which Astroglia never uses;
- re-probed only when the server's command line changes (hash in meta);
- 15 s timeout per server; a server that fails is recorded with the error and skipped next time until it changes.
"""
from __future__ import annotations

import hashlib
import json

import anyio
from pathlib import Path

from .store import Store

TIMEOUT_S = 15


def running_programs() -> set[str]:
    """Lower-case file names of running executables (tasklist on Windows, ps elsewhere). Empty if unknown."""
    import os
    import subprocess
    try:
        if os.name == "nt":
            out = subprocess.run(["tasklist", "/FO", "CSV", "/NH"], capture_output=True, text=True, timeout=10).stdout
            return {line.split('","')[0].strip('"').lower() for line in out.splitlines() if line.startswith('"')}
        out = subprocess.run(["ps", "-eo", "comm="], capture_output=True, text=True, timeout=10).stdout
        return {Path(line.strip()).name.lower() for line in out.splitlines() if line.strip()}
    except (OSError, subprocess.SubprocessError):
        return set()
MAX_TOOLS_IN_SUMMARY = 12


def _signature(meta: dict) -> str:
    return hashlib.sha256(json.dumps(meta.get("target", ""), sort_keys=True).encode()).hexdigest()[:16]


async def _list_tools(command: str, args: list[str], errlog) -> list[dict]:
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client
    with anyio.fail_after(TIMEOUT_S):  # the server's own logs go to errlog, not to the user's terminal
        async with stdio_client(StdioServerParameters(command=command, args=args), errlog=errlog) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                return [{"name": t.name, "description": (t.description or "").strip()} for t in (await s.list_tools()).tools]


def summarize(tools: list[dict]) -> str:
    first = lambda d: d.split("\n")[0].split(". ")[0][:90]
    shown = "; ".join(f"{t['name']}: {first(t['description'])}" if t["description"] else t["name"] for t in tools[:MAX_TOOLS_IN_SUMMARY])
    more = f" (+{len(tools) - MAX_TOOLS_IN_SUMMARY} more)" if len(tools) > MAX_TOOLS_IN_SUMMARY else ""
    return f"Tools ({len(tools)}): {shown}{more}"


def probe(store: Store, claude_json_servers: dict, force: bool = False, only: str | None = None,
          running: set[str] | None = None) -> list[dict]:
    """Probe configured stdio servers; update their nodes. Returns one report line per server.

    Never starts a server whose program is already running: a second copy can disturb the one Claude Code uses
    (some servers clean up shared resources at start-up, e.g. Spectra closes Chrome instances it thinks orphaned)."""
    out = []
    running = running_programs() if running is None else running
    errlog = open(store.path.parent / "probe-servers.log", "a", encoding="utf-8", errors="replace")
    for n in store.nodes(kind="mcp_server", status="active"):
        meta = n["meta"]
        if meta.get("transport", "stdio") != "stdio" or n["title"] == "astroglia" or (only and n["title"] != only):
            continue
        spec = claude_json_servers.get(n["title"])
        if not spec or not spec.get("command"):
            out.append({"server": n["title"], "result": "skipped: command not found in configuration"}); continue
        sig = _signature(meta)
        if Path(spec["command"]).name.lower() in running:
            out.append({"server": n["title"], "result": "skipped: already running (probably used by Claude Code right now). "
                                                         "Probe it when Claude Code is closed, so a second copy cannot disturb it."}); continue
        if not force and meta.get("probe", {}).get("signature") == sig:
            out.append({"server": n["title"], "result": "unchanged since last probe", "tools": meta["probe"].get("count")}); continue
        try:
            tools = anyio.run(_list_tools, spec["command"], [str(a) for a in spec.get("args", [])], errlog)
        except BaseException as e:  # timeouts and anyio groups included; a broken server must not stop the others
            if isinstance(e, KeyboardInterrupt):
                raise
            err = f"{type(e).__name__}: {str(e)[:160]}"
            store.upsert({"id": n["id"], "meta": {**meta, "probe": {"signature": sig, "error": err}}}, op="probe")
            out.append({"server": n["title"], "result": "failed", "error": err}); continue
        base = n["summary"].split(" Tools (")[0]
        store.upsert({"id": n["id"], "summary": f"{base} {summarize(tools)}",
                      "body": "\n".join(f"{t['name']}: {t['description']}" for t in tools),
                      "meta": {**meta, "probe": {"signature": sig, "count": len(tools), "tools": [t["name"] for t in tools]}}},
                     op="probe")
        store.log("probe", server=n["title"], tools=len(tools))
        out.append({"server": n["title"], "result": "ok", "tools": len(tools)})
    errlog.close()
    return out
