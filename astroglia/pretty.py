"""Human-readable output for the CLI. Every command keeps a machine-readable form behind --json."""
from __future__ import annotations

GOLD, DIM, BOLD, RESET, GREEN, RED, YELLOW = "\033[33m", "\033[2m", "\033[1m", "\033[0m", "\033[32m", "\033[31m", "\033[33m"


def _color() -> bool:
    import os
    import sys
    return sys.stdout.isatty() and not os.environ.get("NO_COLOR")


def c(text: str, code: str) -> str:
    return f"{code}{text}{RESET}" if _color() else text


def ok(flag: bool) -> str:
    return c("✓", GREEN) if flag else c("✗", RED)


def welcome(version: str, installed: bool, stats: dict | None, last_sync: str | None) -> str:
    lines = [c(f"Astroglia {version}", BOLD) + " — tells Claude Code which skills and tools fit a task, what it already",
             "learned, and whether that is still true. Local, no LLM calls.", ""]
    if not installed:
        lines += ["Not connected to Claude Code yet. Next step:",
                  "  astroglia install          " + c("# shows what will change", DIM),
                  "  astroglia install --yes    " + c("# connects it (settings.json is backed up)", DIM)]
    elif not stats or not stats.get("nodes_by_kind"):
        lines += ["Connected, but nothing scanned yet. Run:  astroglia sync"]
    else:
        k = stats["nodes_by_kind"]
        caps = sum(k.get(x, 0) for x in ("skill", "command", "agent", "mcp_server", "plugin", "hook"))
        mem = sum(k.get(x, 0) for x in ("experience", "decision", "knowledge"))
        lines += [f"Connected. Knows {caps} capabilities, {k.get('project', 0)} projects and {mem} memory entries"
                  + (f" (last scan {last_sync[:16].replace('T', ' ')} UTC)." if last_sync else "."),
                  "",
                  "  astroglia ui        " + c("# open the Atlas and the dashboards", DIM),
                  "  astroglia value     " + c("# what it actually did for you", DIM),
                  "  astroglia doctor    " + c("# check the installation", DIM)]
    lines += ["", c("All commands: astroglia --help", DIM)]
    return "\n".join(lines)


def install_plan(plan: dict) -> str:
    hooks = plan["hooks_to_set"] or {}
    mine = [e for e, groups in hooks.items() if any("astroglia" in h.get("command", "") for g in groups for h in g.get("hooks", []))]
    return "\n".join([
        c("Dry run — nothing changed.", BOLD),
        f"Would add Astroglia's hooks to {plan['settings_file']} ({', '.join(mine)}),",
        "keeping your other hooks, after backing the file up.",
        "Would register the MCP server:" if plan["claude_cli_found"] else "Would ask you to register the MCP server (claude CLI not found):",
        "  " + plan["mcp_command"],
        "",
        "Apply with:  astroglia install --yes"])


def installed(res: dict, scan: dict | None) -> str:
    lines = [ok(True) + " Hooks added to Claude Code settings" + (f" (backup: {res['settings_backup']})" if res.get("settings_backup") else ""),
             ok(res["mcp_registered"]) + (" MCP server registered" if res["mcp_registered"] else
                                          " MCP server not registered automatically. Run:\n    " + res.get("manual_mcp", ""))]
    if scan:
        lines += ["", c("First scan:", BOLD),
                  f"  {scan['capabilities']} capabilities ({scan['skills']} skills, {scan['mcp']} MCP servers, {scan['plugins']} plugins)",
                  f"  {scan['projects']} projects, {scan['briefs']} project briefs built"]
    lines += ["", "Restart Claude Code: the next session starts with Astroglia's manifest.",
              "Then try:  astroglia ui"]
    return "\n".join(lines)


def doctor(checks: list[dict]) -> str:
    out = []
    for ch in checks:
        optional = "optional" in ch["check"]
        mark = ok(ch["ok"]) if ch["ok"] or not optional else c("·", DIM)
        out.append(f"{mark} {ch['check']}" + (c(f"  {ch['detail']}", DIM) if ch["detail"] else ""))
    return "\n".join(out)


def sync(rep: dict) -> str:
    cap, proj, mem, br = rep["capabilities"], rep["projects"], rep["cc_memory"], rep["briefs"]
    n = lambda r: len(r["created"]) + len(r["updated"]) + r["unchanged"]
    lines = [f"Capabilities: {n(cap)} ({len(cap['created'])} new, {len(cap['missing'])} gone)",
             f"Projects:     {n(proj)} ({len(proj['created'])} new, {len(proj['missing'])} gone)",
             f"Briefs:       {len(br['built'])} rebuilt (sources changed), the others are current",
             f"Claude Code memory files: {n(mem)}"]
    if rep["stale"]:
        lines.append(c(f"{len(rep['stale'])} remembered entr{'ies' if len(rep['stale']) > 1 else 'y'} went stale: sources changed since recorded", YELLOW))
    new = cap["created"] + proj["created"]
    if new:
        lines.append("New: " + ", ".join(i.split(":")[-1] for i in new[:12]) + (f" (+{len(new) - 12})" if len(new) > 12 else ""))
    return "\n".join(lines)


def value(v: dict) -> str:
    m = v["measured"]
    rows = [("project briefs served", m["briefs_served"]), ("memory served at the file", m["anchored_served"]),
            ("déjà vu on errors", m["dejavu_served"]), ("recurring errors flagged", m.get("recurring_flagged", 0)),
            ("memory entries served by routing", m["memory_served"]), ("stale warnings", m["stale_warnings"]),
            ("routings with results", f"{m['routings_with_results']}/{m['routings']}"), ("memories saved", m["memories_saved"]),
            ("duplicates flagged", m["duplicates_flagged"]), ("tool uses learned from", m.get("uses_learned", 0)),
            ("sessions started", m["sessions"])]
    head = c("What Astroglia did" + (f", last {v['period_days']} days" if v.get("period_days") else ""), BOLD) + c("  (measured: counted from the event log)", DIM)
    est = v["estimated"]
    return "\n".join([head] + [f"  {str(val):>7}  {label}" for label, val in rows] +
                     ["", c("Estimate", BOLD) + f": ~{est['tokens_of_rereading_avoided_by_briefs']:,} tokens of re-reading avoided by briefs",
                      c("  formula: " + est["formula"], DIM)])


def status(db: str, last_sync: str | None, stats: dict) -> str:
    k = stats["nodes_by_kind"]
    lines = [f"Database: {db}", f"Last scan: {last_sync or 'never (run astroglia sync)'}", ""]
    lines += [f"  {v:>5}  {kind.replace('_', ' ')}" for kind, v in sorted(k.items(), key=lambda kv: -kv[1])] or ["  empty"]
    rel = sum(stats["edges_by_type"].values())
    lines += ["", f"{rel} relations · {stats['events']} logged events"]
    st = stats["nodes_by_status"]
    if st.get("stale"):
        lines.append(c(f"{st['stale']} stale entries (sources changed)", YELLOW))
    return "\n".join(lines)


def route(r: dict) -> str:
    lines = [c(f"For: {r['task']}", BOLD)]
    if not r["selected"]:
        lines.append("Nothing relevant enough. Astroglia returns nothing rather than noise.")
    for s in r["selected"]:
        lines.append(f"  {s['score']:.2f}  {s['kind']:<10} {s['title']}" + c(f"   {s['id']}", DIM))
        for w in s["warnings"]:
            lines.append(c(f"        ⚠ {w}", YELLOW))
    if r["rejected"]:
        lines += ["", c(f"Rejected ({len(r['rejected'])}):", DIM)]
        lines += [c(f"  {x['title']}: {x['reason']}", DIM) for x in r["rejected"][:6]]
    lines.append(c(f"\n~{r['estimated_tokens']} tokens (estimate) · add --json for the full detail", DIM))
    return "\n".join(lines)


def scan_summary(rep: dict, store) -> dict:
    k = store.stats()["nodes_by_kind"]
    return {"capabilities": sum(k.get(x, 0) for x in ("skill", "command", "agent", "mcp_server", "plugin", "hook")),
            "skills": k.get("skill", 0), "mcp": k.get("mcp_server", 0), "plugins": k.get("plugin", 0),
            "projects": k.get("project", 0), "briefs": len(rep["briefs"]["built"]) + rep["briefs"]["unchanged"]}

