"""Web UI server: access control and versioned mutations over HTTP."""
import json
import threading
import urllib.error
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from astroglia import experiences, web


@pytest.fixture
def server(env):
    httpd = HTTPServer(("127.0.0.1", 0), BaseHTTPRequestHandler)
    port = httpd.server_port
    httpd.RequestHandlerClass = web.make_handler(env["store"], env["cfg"], "tok", port)
    threading.Thread(target=httpd.serve_forever, daemon=True).start()

    def call(path, body=None, token="tok", host=None, headers=None, raw=False):
        req = urllib.request.Request(f"http://127.0.0.1:{port}{path}", method="POST" if body is not None else "GET",
                                     data=json.dumps(body).encode() if body is not None else None,
                                     headers={"X-Astroglia-Token": token, **({"Host": host} if host else {}), **(headers or {})})
        try:
            with urllib.request.urlopen(req) as r:
                return (r.status, r.read(), r.headers) if raw else (r.status, r.read())
        except urllib.error.HTTPError as e:
            return e.code, e.read()
    yield call
    httpd.shutdown(); httpd.server_close()


def test_static_page_served_but_api_needs_token_and_local_host(server):
    code, page = server("/", token="")
    assert code == 200 and b"<title>Astroglia</title>" in page
    for asset in ("/app.js", "/galaxy.js", "/style.css"):
        assert server(asset, token="")[0] == 200
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


def test_graph_voids_and_live_events(server, env):
    s = env["store"]
    src = env["tmp"] / "f.py"; src.write_text("x = 1\n", encoding="utf-8")
    a = experiences.remember(s, "Tied to a file", "will go stale", files=[str(src)])
    b = experiences.remember(s, "No files", "cannot be verified", confidence=0.3)
    g = json.loads(server("/api/graph")[1])
    assert {a["id"], b["id"]} <= {n["id"] for n in g["nodes"]}
    src.write_text("x = 2\n", encoding="utf-8")
    experiences.verify(s, a["id"])
    v = {x["key"]: [i["id"] for i in x["items"]] for x in json.loads(server("/api/voids")[1])}
    assert v["stale"] == [a["id"]]
    assert b["id"] in v["unverifiable"] and b["id"] in v["low-confidence"] and b["id"] in v["isolated"]
    s.log("route", task="t", selected=[a["id"]])
    new = json.loads(server(f"/api/events?after={g['last_event']}")[1])
    assert [e["kind"] for e in new][-1] == "route" and all(e["id"] > g["last_event"] for e in new)


def test_large_json_is_gzipped_when_accepted(server, env):
    import gzip as gz
    for i in range(300):
        experiences.remember(env["store"], f"entry {i} about caching and websockets", "x" * 80)
    code, body, headers = server("/api/graph", headers={"Accept-Encoding": "gzip"}, raw=True)
    assert code == 200 and headers["Content-Encoding"] == "gzip"
    plain = gz.decompress(body)
    assert len(json.loads(plain)["nodes"]) >= 300 and len(body) < len(plain) / 3
    code, body = server("/api/graph")  # clients that do not ask for gzip get plain JSON
    assert json.loads(body)["nodes"]


def test_reveal_only_opens_recorded_existing_paths(server, env, monkeypatch):
    calls = []
    monkeypatch.setattr(web.subprocess, "Popen", lambda args: calls.append(args))
    f = env["tmp"] / "note.md"; f.write_text("x", encoding="utf-8")
    env["store"].upsert({"id": "knowledge:x", "kind": "knowledge", "title": "x", "source": "test", "ref": str(f)})
    assert server("/api/reveal", {"id": "knowledge:x"})[0] == 200 and str(f) in calls[0]
    assert server("/api/reveal", {"id": "knowledge:unknown"})[0] == 404
    f.unlink()
    assert server("/api/reveal", {"id": "knowledge:x"})[0] == 404 and len(calls) == 1
