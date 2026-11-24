"""The user-facing scenarios from the spec, end to end on a fake Claude Code install."""
import io
import json

from astroglia import capabilities, experiences, hooks, router
from astroglia.store import Store

from conftest import skill, write


def sync(env):
    c = env["cfg"]
    return capabilities.sync(env["store"], c.claude_dir, c.claude_json, [], c.redundancy_threshold)


def test_discovers_every_capability_kind(env):
    rep = sync(env)
    ids = set(rep["created"])
    assert {"plugin:csvkit@local", "skill:csvkit@local:csv-analyze", "command:csvkit@local:csv-clean",
            "skill:user:python-review", "mcp_server:user:db"} <= ids
    assert any(i.startswith("hook:csvkit@local:SessionStart") for i in ids)
    assert env["store"].edges("skill:csvkit@local:csv-analyze", type="belongs_to")[0]["dst"] == "plugin:csvkit@local"


def test_mcp_env_values_are_never_stored(env):
    sync(env)
    n = env["store"].get("mcp_server:user:db")
    assert n["meta"]["env_keys"] == ["DB_PASSWORD"]
    assert "hunter2" not in json.dumps(n)


def test_scenario3_new_capability_detected_incrementally(env):
    sync(env)
    skill(env["claude"] / "skills", "pdf-forms", "Fill PDF forms automatically.")
    rep = sync(env)
    assert rep["created"] == ["skill:user:pdf-forms"]
    assert rep["unchanged"] > 0 and rep["updated"] == []
    (env["claude"] / "skills" / "pdf-forms" / "SKILL.md").unlink()
    rep = sync(env)
    assert rep["missing"] == ["skill:user:pdf-forms"]
    assert env["store"].get("skill:user:pdf-forms")["status"] == "missing"  # flagged, not deleted


def test_scenario4_routing_skips_redundant_capability_and_explains(env):
    sync(env)
    assert env["store"].edges("skill:csvkit@local:csv-analyze", type="similar_to")
    r = router.route(env["store"], env["cfg"], "analyze statistics of a CSV spreadsheet file")
    sel = [s["id"] for s in r["selected"]]
    assert len({"skill:csvkit@local:csv-analyze", "skill:csvkit@local:csv-profile"} & set(sel)) == 1
    assert any("redundant with" in x["reason"] for x in r["rejected"])
    assert all(set(s["why"]) == {"relevance", "named", "confidence", "freshness", "success", "project"} for s in r["selected"])
    assert "plugin:csvkit@local" not in sel  # containers are not routed


def test_unrelated_task_selects_nothing(env):
    sync(env)
    r = router.route(env["store"], env["cfg"], "chocolate cake recipe for a birthday")
    assert r["selected"] == []


def test_scenario5_experience_reused_then_flagged_stale(env):
    src = write(env["tmp"] / "app" / "sync.py", "def sync(): retry = 3\n")
    e = experiences.remember(env["store"], "Fixed sync race condition in app",
                             "Sync dropped writes; fixed by holding the lock across flush and retrying 3 times.",
                             body="Root cause: flush outside lock.", project="app", files=[str(src)])
    r = router.route(env["store"], env["cfg"], "comment avait-on corrigé le problème de synchronisation ?", project="app")
    top = r["selected"][0]
    assert top["id"] == e["id"] and top["warnings"] == [] and top["why"]["project"] == 1.0
    src.write_text("def sync(): retry = 5\n", encoding="utf-8")
    r = router.route(env["store"], env["cfg"], "sync race condition fix", project="app")
    assert r["selected"][0]["warnings"][0].startswith("STALE")
    assert env["store"].get(e["id"])["status"] == "stale"
    experiences.revalidate(env["store"], e["id"])
    assert experiences.verify(env["store"], e["id"])["status"] == "active"


def test_secrets_are_refused(env):
    import pytest
    with pytest.raises(ValueError, match="secret"):
        experiences.remember(env["store"], "deploy", "deploy notes", body="api_key = sk-abcdefghijklmnopqrstuvwxyz123")


def test_history_and_restore(env):
    s = env["store"]
    e = experiences.remember(s, "Use WAL", "SQLite in WAL mode for concurrent reads", kind="decision")
    experiences.remember(s, "Use WAL", "Changed my mind: rollback journal", kind="decision", node_id=e["id"])
    h = s.history(e["id"])
    assert h[0]["snapshot"]["summary"] == "SQLite in WAL mode for concurrent reads"
    s.restore(h[0]["history_id"])
    assert s.get(e["id"])["summary"] == "SQLite in WAL mode for concurrent reads"
    assert s.delete(e["id"]) and s.get(e["id"]) is None
    s.restore(s.history(e["id"])[0]["history_id"])  # even a delete is reversible
    assert s.get(e["id"]) is not None


def test_feedback_changes_ranking_signal(env):
    sync(env)
    before = router.route(env["store"], env["cfg"], "review python code")["selected"][0]
    router.feedback(env["store"], [before["id"]], useful=False)
    router.feedback(env["store"], [before["id"]], useful=False)
    after = router.route(env["store"], env["cfg"], "review python code")["selected"][0]
    assert after["why"]["success"] < before["why"]["success"]


def test_budget_is_respected(env):
    sync(env)
    r = router.route(env["store"], env["cfg"], "csv spreadsheet python review", budget=40)
    assert r["estimated_tokens"] <= 40
    assert any(x["reason"].startswith("budget") for x in r["rejected"])


def test_session_start_manifest(env):
    out = hooks.session_start({"cwd": str(env["tmp"])}, env["cfg"])
    assert out.startswith("[Astroglia]") and "Capabilities:" in out and "route" in out
    assert len(out) < 2000  # stays a light manifest
    skill(env["claude"] / "skills", "brand-new", "Something new.")
    assert "brand-new" in hooks.session_start({}, env["cfg"])


def test_scenario6_hook_fails_open(env, monkeypatch, capsys):
    # Corrupt database: hook must print nothing and exit 0 so Claude Code continues normally.
    env["store"].close()
    env["cfg"].db_path.write_bytes(b"this is not a sqlite file" * 100)
    for f in env["cfg"].home.glob("astroglia.db-*"):
        f.unlink()
    monkeypatch.setattr("sys.stdin", io.StringIO('{"cwd": "."}'))
    assert hooks.run("session-start") == 0
    assert capsys.readouterr().out == ""
    assert (env["cfg"].home / "hook-errors.log").exists()
    env["store"] = Store(env["tmp"] / "other.db")  # for fixture teardown


def test_backup_roundtrip(env):
    experiences.remember(env["store"], "Keep me", "important fact")
    b = env["store"].backup(env["tmp"] / "b.db")
    copy = Store(b)
    assert copy.stats()["nodes_by_kind"]["experience"] == 1
    copy.close()


def test_deleted_source_file_keeps_entry_stale_and_blocks_revalidation(env):
    import pytest
    src = write(env["tmp"] / "gone.py", "x = 1\n")
    e = experiences.remember(env["store"], "Depends on gone.py", "fact about gone.py", files=[str(src)])
    src.unlink()
    assert experiences.verify(env["store"], e["id"])["status"] == "stale"
    with pytest.raises(ValueError, match="no longer exist"):
        experiences.revalidate(env["store"], e["id"])
    assert experiences.verify(env["store"], e["id"])["status"] == "stale"


def _transcript(tmp, tools):
    lines = [json.dumps({"type": "assistant", "message": {"content": [{"type": "tool_use", "name": n, "input": i}]}}) for n, i in tools]
    p = tmp / "t.jsonl"; p.write_text("\n".join(lines), encoding="utf-8")
    return str(p)


def test_consolidation_asks_once_after_real_work(env):
    a = write(env["tmp"] / "a.py", "x\n")
    t = _transcript(env["tmp"], [("Edit", {"file_path": str(a)}), ("Write", {"file_path": "gone.py"}), ("Read", {"file_path": "c.py"})])
    out = hooks.stop({"transcript_path": t, "session_id": "s1"}, env["cfg"])
    assert out["decision"] == "block" and "edited 2 files" in out["reason"] and "remember" in out["reason"]
    assert f"- {a}" in out["reason"] and "- (+1 more)" in out["reason"]  # full paths, deleted files left out
    assert hooks.stop({"transcript_path": t, "session_id": "s1"}, env["cfg"]) is None          # once per session
    assert hooks.stop({"transcript_path": t, "session_id": "s2", "stop_hook_active": True}, env["cfg"]) is None  # no loop


def test_consolidation_stays_quiet_when_not_needed(env):
    small = _transcript(env["tmp"], [("Edit", {"file_path": "a.py"})])
    assert hooks.stop({"transcript_path": small, "session_id": "s3"}, env["cfg"]) is None      # below threshold
    saved = _transcript(env["tmp"], [("Edit", {"file_path": "a.py"}), ("Edit", {"file_path": "b.py"}),
                                     ("mcp__astroglia__remember", {"title": "x"})])
    assert hooks.stop({"transcript_path": saved, "session_id": "s4"}, env["cfg"]) is None      # already saved
    env["cfg"].consolidate = False
    big = _transcript(env["tmp"], [("Edit", {"file_path": f"{i}.py"}) for i in range(5)])
    assert hooks.stop({"transcript_path": big, "session_id": "s5"}, env["cfg"]) is None        # disabled by config


def test_value_report_counts_what_was_served(env):
    from astroglia import metrics
    s = env["store"]
    src = write(env["tmp"] / "m.py", "x = 1\n")
    experiences.remember(s, "Websocket reconnect fix", "Retry with backoff after close event", files=[str(src)])
    experiences.remember(s, "Websocket reconnect fix again", "Retry with backoff after the close event fires")
    router.route(s, env["cfg"], "websocket reconnect")
    src.write_text("x = 2\n", encoding="utf-8")
    router.route(s, env["cfg"], "websocket reconnect")
    s.log("served", id="knowledge:brief:p", kind="brief", via="wake", bytes=4000)
    v = metrics.value(s)
    m = v["measured"]
    assert m["routings"] == 2 and m["memory_served"] >= 3 and m["stale_warnings"] >= 1
    assert m["memories_saved"] == 2 and m["duplicates_flagged"] == 1 and m["briefs_served"] == 1
    assert v["estimated"]["tokens_of_rereading_avoided_by_briefs"] == 1000 and "formula" in v["estimated"]
    assert metrics.value(s, days=1)["measured"]["routings"] == 2


def test_consolidation_counts_cli_saves(env):
    t = _transcript(env["tmp"], [("Edit", {"file_path": "a.py"}), ("Edit", {"file_path": "b.py"}),
                                 ("Bash", {"command": ".venv/Scripts/astroglia remember \"x\" \"y\" --file a.py"})])
    assert hooks.stop({"transcript_path": t, "session_id": "s6"}, env["cfg"]) is None


def test_everyday_words_and_known_services_reach_the_right_tool(env):
    from astroglia import capabilities
    from astroglia.text import terms
    assert "task" in terms("my todo list") and "spreadsheet" in terms("a workbook")
    assert capabilities.describe_service("gmail").startswith("Email")
    assert capabilities.describe_service("my-internal-thing") is None   # unknown names get no invented description
    s = env["store"]
    s.upsert({"id": "mcp_server:user:gmail", "kind": "mcp_server", "title": "gmail", "source": "scan:claude-code",
              "summary": capabilities.describe_service("gmail") + ". MCP server (http): https://example"})
    r = router.route(s, env["cfg"], "mail the client the invoice")
    assert r["selected"][0]["id"] == "mcp_server:user:gmail"
