"""The user-facing scenarios from the spec, end to end on a fake Claude Code install."""
import io
import json

from nexus import capabilities, experiences, hooks, router
from nexus.store import Store

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
    assert all(set(s["why"]) == {"relevance", "confidence", "freshness", "success", "project"} for s in r["selected"])
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
    assert out.startswith("[NEXUS]") and "Capabilities:" in out and "nexus_route" in out
    assert len(out) < 2000  # stays a light manifest
    skill(env["claude"] / "skills", "brand-new", "Something new.")
    assert "brand-new" in hooks.session_start({}, env["cfg"])


def test_scenario6_hook_fails_open(env, monkeypatch, capsys):
    # Corrupt database: hook must print nothing and exit 0 so Claude Code continues normally.
    env["store"].close()
    env["cfg"].db_path.write_bytes(b"this is not a sqlite file" * 100)
    for f in env["cfg"].home.glob("nexus.db-*"):
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
