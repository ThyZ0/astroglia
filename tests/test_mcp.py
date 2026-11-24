"""MCP server: tools are registered and callable through the real protocol over stdio."""
import json
import os
import sys

import anyio
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

EXPECTED = {"route", "search", "get", "remember", "feedback", "revalidate",
            "link", "capabilities", "status", "sync", "project", "changes", "health"}


def test_mcp_stdio_roundtrip(env):
    async def go():
        params = StdioServerParameters(command=sys.executable, args=["-m", "astroglia", "mcp"],
                                       env={**os.environ, "ASTROGLIA_HOME": str(env["cfg"].home)})
        async with stdio_client(params) as (r, w):
            async with ClientSession(r, w) as s:
                await s.initialize()
                tools = {t.name for t in (await s.list_tools()).tools}
                assert EXPECTED <= tools
                res = await s.call_tool("remember", {"title": "MCP works", "summary": "stdio roundtrip verified"})
                data = json.loads(res.content[0].text)
                assert data["result"] == "created"
                res = await s.call_tool("route", {"task": "mcp stdio roundtrip"})
                route = json.loads(res.content[0].text)
                assert route["selected"][0]["id"] == data["id"]
                assert "untrusted" in route["notice"]
    anyio.run(go)
