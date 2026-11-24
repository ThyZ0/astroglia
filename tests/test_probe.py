"""probe: learn what a local MCP server does from its own tool list."""
import json
import sys

from astroglia import capabilities, probe, router

FAKE_SERVER = '''from mcp.server.mcpserver import MCPServer
m = MCPServer("fake")


@m.tool(name="callers")
async def callers(symbol: str) -> str:
    """Find every function that calls a symbol, and what breaks if it is renamed."""
    return ""


m.run("stdio")
'''


def test_probe_learns_tools_and_sync_keeps_them(env):
    srv = env["tmp"] / "fake_mcp.py"
    srv.write_text(FAKE_SERVER, encoding="utf-8")
    cj = json.loads(env["cfg"].claude_json.read_text(encoding="utf-8"))
    cj["mcpServers"]["codemap"] = {"type": "stdio", "command": sys.executable, "args": [str(srv)]}
    env["cfg"].claude_json.write_text(json.dumps(cj), encoding="utf-8")
    sync = lambda: capabilities.sync(env["store"], env["cfg"].claude_dir, env["cfg"].claude_json)
    sync()
    rep = {r["server"]: r for r in probe.probe(env["store"], cj["mcpServers"])}
    assert rep["codemap"]["result"] == "ok" and rep["codemap"]["tools"] == 1
    assert rep["db"]["result"] == "failed"                      # a missing program is recorded, not fatal
    n = env["store"].get("mcp_server:user:codemap")
    assert "callers" in n["summary"] and "renamed" in n["body"]
    sync()                                                       # a normal sync must not erase what was learned
    assert "callers" in env["store"].get("mcp_server:user:codemap")["summary"]
    again = {r["server"]: r["result"] for r in probe.probe(env["store"], cj["mcpServers"])}
    assert again["codemap"] == "unchanged since last probe" and again["db"] == "unchanged since last probe"
    r = router.route(env["store"], env["cfg"], "who calls this function and what breaks if I rename it")
    assert r["selected"][0]["id"] == "mcp_server:user:codemap"
