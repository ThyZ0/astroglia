"""Anchored memory: knowledge served when Claude reads or edits the file it is about."""
import io
import json

from astroglia import anchors, experiences, providers

from conftest import write


def call(env, tool, path, session="s1"):
    return anchors.respond({"tool_name": tool, "tool_input": {"file_path": str(path)}, "session_id": session},
                           env["cfg"].db_path)


def test_read_serves_memory_once_per_session_and_flags_staleness(env):
    src = write(env["tmp"] / "app" / "cache.py", "TTL = 600\n")
    d = experiences.remember(env["store"], "Cache TTL is 10 minutes", "Providers rate-limit at 60/h.", kind="decision",
                             files=[str(src)])
    out = call(env, "Read", src)
    assert "Cache TTL is 10 minutes" in out and d["id"] in out and "STALE" not in out
    assert call(env, "Read", src) is None                      # once per file per session
    src.write_text("TTL = 300\n", encoding="utf-8")
    out = call(env, "Read", src, session="s2")
    assert "STALE" in out                                       # changed since recorded, even before any sync


def test_edit_warns_about_dependent_entries_once(env):
    src = write(env["tmp"] / "billing.py", "x = 1\n")
    other = write(env["tmp"] / "billing_v2.py", "x = 1\n")
    d = experiences.remember(env["store"], "Invoices round per line", "Rounding happens per line, not on the total.",
                             kind="decision", files=[str(src)])
    out = call(env, "Edit", src)
    assert "may no longer hold" in out and d["id"] in out and "revalidate" in out
    assert call(env, "Write", src) is None                      # same entry, same session: once
    assert call(env, "Edit", other) is None                     # longer/similar path is not the same file


def test_generated_entries_and_unknown_files_stay_silent(env, monkeypatch):
    root = env["tmp"] / "proj"
    write(root / "package.json", json.dumps({"name": "p", "scripts": {"test": "x"}}))
    write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
    env["cfg"].project_roots = [str(root)]
    providers.sync(env["store"], env["cfg"])                    # builds a brief anchored to package.json
    assert env["store"].get("knowledge:brief:proj")
    assert call(env, "Read", root / "package.json") is None     # briefs are not claims: not served
    assert call(env, "Read", env["tmp"] / "nothing.py") is None
    assert anchors.respond({"tool_name": "Bash", "tool_input": {"command": "ls"}}, env["cfg"].db_path) is None


def test_hook_entry_point_fails_open(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("not json"))
    assert anchors.run() == 0 and capsys.readouterr().out == ""


def test_served_anchors_count_in_value_report(env):
    from astroglia import metrics
    src = write(env["tmp"] / "a.py", "y = 1\n")
    experiences.remember(env["store"], "A fact", "about a.py", files=[str(src)])
    call(env, "Read", src)
    assert metrics.value(env["store"])["measured"]["anchored_served"] == 1
