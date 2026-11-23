"""Local web UI: a stdlib HTTP server over the same store as the CLI and MCP server.

Security: binds 127.0.0.1 only; every /api call needs the per-run token (sent by the page as
X-Nexus-Token) and a localhost Host header, so other web pages cannot drive the API
(CSRF / DNS rebinding). All mutations go through Store methods, so they are versioned and logged.
"""
from __future__ import annotations

import json
import secrets
import webbrowser
from collections import Counter
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from . import __version__, config, experiences, providers, router
from .store import EDGE_TYPES, Store

UI_DIR = Path(__file__).parent / "ui"
STATIC = {"/": ("index.html", "text/html"), "/app.js": ("app.js", "text/javascript"),
          "/style.css": ("style.css", "text/css")}
EDITABLE = ("title", "summary", "body", "tags", "confidence", "importance", "status", "project")


def merge(store: Store, src: str, dst: str) -> dict:
    """Fold entry `src` into `dst`: texts appended, relations re-pointed, src deleted (kept in history)."""
    a, b = store.get(src), store.get(dst)
    if not a or not b or src == dst:
        raise ValueError("merge needs two different existing ids")
    files = {**(b["fingerprint"] or {}), **(a["fingerprint"] or {})}
    body = "\n\n".join(x for x in (b["body"], f"[merged from {a['title']}]\n{a['summary']}\n{a['body'] or ''}".strip()) if x)
    tags = " ".join(dict.fromkeys((b["tags"] + " " + a["tags"]).split()))
    store.upsert({"id": dst, "body": body, "tags": tags, "fingerprint": files or None,
                  "meta": {**b["meta"], "files": list(files), "merged": b["meta"].get("merged", []) + [src]}}, op=f"merge:{src}")
    for e in store.edges(src):
        s, d = (dst if e["src"] == src else e["src"]), (dst if e["dst"] == src else e["dst"])
        if s != d:
            store.link(s, d, e["type"], source=e["source"], confidence=e["confidence"])
    store.delete(src)
    store.log("memory.merged", src=src, dst=dst)
    return {"merged": src, "into": dst}


def overview(store: Store) -> dict:
    st = store.stats()
    days = Counter(e["ts"][:10] for e in store.events(5000))
    routes = store.events(500, kind="route")
    return {**st, "version": __version__, "last_capability_sync": store.kv_get("last_capability_sync"),
            "sessions": int(store.kv_get("sessions_seen", "0")),
            "activity": sorted(days.items())[-30:],
            "routes": len(routes),
            "avg_selected": round(sum(len(r["payload"].get("selected", [])) for r in routes) / len(routes), 2) if routes else None,
            "avg_est_tokens": round(sum(r["payload"].get("estimated_tokens", 0) for r in routes) / len(routes)) if routes else None}


def api(store: Store, cfg: config.Config, method: str, path: str, q: dict, body: dict):
    one = lambda k, d=None: (q.get(k) or [d])[0]
    if method == "GET":
        if path == "/api/overview":
            return overview(store)
        if path == "/api/nodes":
            kinds = one("kinds", "")
            rows = [n for n in store.nodes() if not kinds or n["kind"] in kinds.split(",")]
            return [{k: n[k] for k in ("id", "kind", "title", "summary", "status", "project", "confidence", "uses",
                                       "successes", "verified", "ref", "tags")} | {"origin": n["meta"].get("origin")}
                    for n in rows]
        if path == "/api/edges":
            return store.edges(type=one("type"))
        if path == "/api/node":
            n = store.get(one("id", ""))
            if n is None:
                return 404, {"error": "unknown id"}
            if n["fingerprint"]:
                n["validity"] = experiences.verify(store, n["id"])
            return {"node": n, "edges": store.edges(n["id"]), "history": store.history(n["id"])[:30]}
        if path == "/api/events":
            return store.events(int(one("limit", "100")), kind=one("kind"))
        if path == "/api/project":
            return providers.project_card(store, one("ref", "")) or (404, {"error": "unknown project"})
        if path == "/api/edge-types":
            return sorted(EDGE_TYPES)
    if method == "POST":
        if path == "/api/route":
            r = router.route(store, cfg, str(body.get("task", "")), project=body.get("project") or None,
                             budget=int(body.get("budget") or 1200))
            return r
        if path == "/api/node":
            fields = {k: body[k] for k in EDITABLE if k in body}
            if not store.get(str(body.get("id"))):
                return 404, {"error": "unknown id"}
            text = " ".join(str(fields.get(k, "")) for k in ("title", "summary", "body"))
            if experiences.find_secret(text):
                return 400, {"error": "refused: looks like a secret"}
            for k in ("confidence", "importance"):
                if k in fields:
                    fields[k] = min(1.0, max(0.0, float(fields[k])))
            return {"result": store.upsert({"id": body["id"], **fields}, op="ui-edit")}
        if path == "/api/delete":
            return {"deleted": store.delete(str(body.get("id")))}
        if path == "/api/restore":
            return {"result": store.restore(int(body["history_id"]))}
        if path == "/api/merge":
            return merge(store, str(body.get("src")), str(body.get("dst")))
        if path == "/api/link":
            if not (store.get(body.get("src", "")) and store.get(body.get("dst", ""))):
                return 400, {"error": "both ids must exist"}
            store.link(body["src"], body["dst"], body["type"], source="user", confidence=1.0)
            return {"linked": True}
        if path == "/api/unlink":
            store.unlink(body["src"], body["dst"], body["type"])
            return {"unlinked": True}
        if path == "/api/revalidate":
            return experiences.revalidate(store, str(body.get("id")))
        if path == "/api/feedback":
            return router.feedback(store, list(body.get("ids", [])), bool(body.get("useful")))
        if path == "/api/sync":
            rep = providers.sync_all(store, cfg)
            return {k: {kk: (vv if isinstance(vv, int) else len(vv)) for kk, vv in v.items()} if isinstance(v, dict) else v
                    for k, v in rep.items()}
    return 404, {"error": f"no route {method} {path}"}


def make_handler(store: Store, cfg: config.Config, token: str, port: int):
    allowed_hosts = {f"127.0.0.1:{port}", f"localhost:{port}"}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):  # keep the terminal quiet
            pass

        def _send(self, code: int, payload, ctype="application/json"):
            data = payload if isinstance(payload, bytes) else json.dumps(payload, ensure_ascii=False, default=str).encode()
            self.send_response(code)
            self.send_header("Content-Type", f"{ctype}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Content-Security-Policy", "default-src 'self'; style-src 'self'; img-src 'self' data:")
            self.end_headers()
            self.wfile.write(data)

        def _handle(self, method: str):
            if self.headers.get("Host") not in allowed_hosts:
                return self._send(403, {"error": "bad host"})
            url = urlparse(self.path)
            if method == "GET" and url.path in STATIC:
                name, ctype = STATIC[url.path]
                return self._send(200, (UI_DIR / name).read_bytes(), ctype)
            if not url.path.startswith("/api/"):
                return self._send(404, {"error": "not found"})
            if not secrets.compare_digest(self.headers.get("X-Nexus-Token", ""), token):
                return self._send(401, {"error": "missing or bad token"})
            body = {}
            if method == "POST":
                try:
                    body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
                except ValueError:
                    return self._send(400, {"error": "invalid JSON"})
            try:
                out = api(store, cfg, method, url.path, parse_qs(url.query), body)
            except (ValueError, KeyError, TypeError) as e:
                return self._send(400, {"error": str(e)})
            code, out = out if isinstance(out, tuple) else (200, out)
            self._send(code, out)

        def do_GET(self):
            self._handle("GET")

        def do_POST(self):
            self._handle("POST")

    return Handler


def serve(cfg: config.Config, port: int = 8765, open_browser: bool = True) -> None:
    store = Store(cfg.db_path)
    token = secrets.token_urlsafe(24)
    httpd = HTTPServer(("127.0.0.1", port), BaseHTTPRequestHandler)
    port = httpd.server_port  # resolves port 0 to the real one
    httpd.RequestHandlerClass = make_handler(store, cfg, token, port)
    url = f"http://127.0.0.1:{port}/#token={token}"
    print(f"NEXUS UI on {url}  (Ctrl+C to stop)", flush=True)
    if open_browser:
        webbrowser.open(url)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        store.close()
