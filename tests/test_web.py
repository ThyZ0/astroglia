"""Web UI server: access control and versioned mutations over HTTP."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from nexus import experiences, web


@pytest.fixture
def server(env):
    httpd = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = httpd.server_port
    httpd.RequestHandlerClass = web.make_handler(env["store"], env["cfg"], "tok", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(path, body=None, token="tok", host=None):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Nexus-Token": token, **({"Host": host} if host else {})})
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    yield call
    httpd.shutdown(); httpd.server_close()


def test_static_page_served_but_api_needs_token_and_local_host(server):
    code, page = server("/", token="")
    assert code == 200 and b"<title>NEXUS</title>" in page
    assert server("/api/overview", token="")[0] == 401
    assert server("/api/overview", token="wrong")[0] == 401
    assert server("/api/overview", host="evil.example:80")[0] == 403  # DNS-rebinding guard
    code, body = server("/api/overview")
    assert code == 200 and "nodes_by_kind" in json.loads(body)


def test_edit_refuses_secrets_and_is_versioned(server, env):
    e = experiences.remember(env["store"], "Deploy", "How we deploy")
    assert server("/api/node", {"id": e["id"], "body": "password = hunter2hunter2"})[0] == 400
    assert server("/api/node", {"id": e["id"], "summary": "How we deploy (updated)", "confidence": 7})[0] == 200
    n = env["store"].get(e["id"])
    assert n["summary"] == "How we deploy (updated)" and n["confidence"] == 1.0  # clamped
    hist = json.loads(server(f"/api/node?id={e['id']}")[1])["history"]
    server("/api/restore", {"history_id": hist[0]["history_id"]})
    assert env["store"].get(e["id"])["summary"] == "How we deploy"


def test_merge_folds_entry_and_keeps_it_restorable(server, env):
    s = env["store"]
    a = experiences.remember(s, "Sync bug A", "Lock across flush", tags=["sync"])
    b = experiences.remember(s, "Sync bug B", "Retry three times", tags=["retry"])
    c = experiences.remember(s, "Other", "Unrelated")
    s.link(a["id"], c["id"], "related_to", source="agent")
    assert server("/api/merge", {"src": a["id"], "dst": b["id"]})[0] == 200
    merged = s.get(b["id"])
    assert "Lock across flush" in merged["body"] and "sync" in merged["tags"].split()
    assert s.get(a["id"]) is None and s.history(a["id"])[0]["op"] == "delete"
    assert any(e["dst"] == c["id"] for e in s.edges(b["id"]))  # relation re-pointed
    assert server("/api/merge", {"src": b["id"], "dst": b["id"]})[0] == 400


def test_route_from_ui_is_logged_for_context_monitor(server, env):
    experiences.remember(env["store"], "Flaky websocket test", "Fixed by awaiting the server ready event")
    r = json.loads(server("/api/route", {"task": "flaky websocket test"})[1])
    assert r["selected"] and r["route_id"]
    ev = json.loads(server("/api/events?kind=route")[1])
    assert ev[0]["payload"]["task"] == "flaky websocket test"
