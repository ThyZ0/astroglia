"""Déjà vu: a failed command matched against remembered fixes."""
import io

from astroglia import dejavu, experiences


def fail(env, error, session="s1"):
    return dejavu.respond({"tool_name": "Bash", "error": error, "session_id": session}, env["cfg"].db_path)


def test_recognises_an_error_already_solved(env):
    e = experiences.remember(env["store"], "httpx ReadTimeout from provider B",
                             "Provider B times out under load (httpx.ReadTimeout). Fixed with httpx retries and backoff, 3 tries.")
    out = fail(env, "Exit code 1\nTraceback (most recent call last):\n  File \"C:\\app\\fetch.py\", line 42\n"
                    "httpx.ReadTimeout: provider B timed out after 30.0s")
    assert out and e["id"] in out and "Déjà vu" in out and "readtimeout" in out
    assert fail(env, "Exit code 1\nhttpx.ReadTimeout: provider B timed out") is None      # once per entry per session


def test_stays_silent_on_weak_or_generic_matches(env):
    experiences.remember(env["store"], "Release checklist", "Run the tests, update the changelog, tag the version.")
    assert fail(env, "Exit code 1\nError: tests failed") is None                            # only generic words
    assert fail(env, "Exit code 2\nerror: could not find file /src/app/main.rs at line 12") is None
    assert fail(env, "") is None
    assert dejavu.respond({"error": "x", "is_interrupt": True}, env["cfg"].db_path) is None


def test_generated_entries_are_not_served_as_fixes(env):
    env["store"].upsert({"id": "knowledge:brief:p", "kind": "knowledge", "title": "p: project brief", "source": "provider:brief",
                         "summary": "ModuleNotFoundError appears when the venv lacks httpx and pydantic"})
    assert fail(env, "ModuleNotFoundError: No module named 'httpx' (pydantic import)") is None


def test_signature_drops_paths_numbers_and_generic_words():
    sig = dejavu.signature("Exit code 1\nFile \"C:\\Users\\me\\proj\\app.py\", line 42\nModuleNotFoundError: No module named 'pydantic_core'")
    assert "modulenotfounderror" in sig and "pydantic_core" in sig
    assert not ({"exit", "code", "line", "users", "proj", "42"} & sig)


def test_hook_entry_fails_open(env, monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin", io.StringIO("{broken"))
    assert dejavu.run() == 0 and capsys.readouterr().out == ""


def test_consolidation_quotes_errors_met_in_the_session(env, tmp_path):
    import json
    from astroglia import hooks
    a = tmp_path / "a.py"; a.write_text("x", encoding="utf-8")
    b = tmp_path / "b.py"; b.write_text("x", encoding="utf-8")
    lines = [
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": str(a)}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                                                  "content": "Exit code 1\nTraceback...\nsqlite3.OperationalError: database is locked"}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": str(b)}}]}},
    ]
    t = tmp_path / "t.jsonl"; t.write_text("\n".join(json.dumps(x) for x in lines), encoding="utf-8")
    out = hooks.stop({"transcript_path": str(t), "session_id": "e1"}, env["cfg"])
    assert "sqlite3.OperationalError: database is locked" in out["reason"]


def test_installer_adds_the_failure_hook_for_shell_tools_only(env, monkeypatch):
    import json
    from astroglia import cli
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    cli.main(["--home", str(env["cfg"].home), "install", "--yes"])
    s = json.loads((env["claude"] / "settings.json").read_text(encoding="utf-8"))
    g = s["hooks"]["PostToolUseFailure"][0]
    assert g["matcher"] == "Bash|PowerShell" and "hook failure" in g["hooks"][0]["command"]
