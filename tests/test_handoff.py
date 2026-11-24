"""Handoff: where the last session in a project left off, shown when the next one starts there."""
import json

from astroglia import hooks, providers

from conftest import write


def _project(env, monkeypatch):
    monkeypatch.setattr(providers, "cortex_projects", lambda: [])
    root = env["tmp"] / "shop"
    write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(root / "package.json", json.dumps({"name": "shop"}))
    env["cfg"].project_roots = [str(root)]
    providers.sync(env["store"], env["cfg"])
    return root


def _transcript(tmp, root):
    rows = [
        {"type": "user", "message": {"role": "user", "content": "<task-notification>ignored</task-notification>"}},
        {"type": "user", "message": {"role": "user", "content": "fix the cart total when a discount code is applied"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": str(root / "cart.ts")}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True, "content": "Exit code 1\nTypeError: total is not a function"}]}},
    ]
    t = tmp / "t.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(t)


def test_next_session_in_the_project_sees_where_the_last_one_stopped(env, monkeypatch):
    root = _project(env, monkeypatch)
    env["cfg"].consolidate = False
    hooks.stop({"transcript_path": _transcript(env["tmp"], root), "session_id": "s1", "cwd": str(root)}, env["cfg"])
    out = hooks.session_start({"cwd": str(root), "session_id": "s2"}, env["cfg"])
    assert "Last session here" in out and "fix the cart total" in out and "cart.ts" in out and "TypeError" in out
    assert "task-notification" not in out
    same = hooks.session_start({"cwd": str(root), "session_id": "s1"}, env["cfg"])   # resuming the same session
    assert "Last session here" not in same


def test_no_handoff_without_work_or_outside_projects(env, monkeypatch):
    root = _project(env, monkeypatch)
    empty = env["tmp"] / "e.jsonl"
    empty.write_text(json.dumps({"type": "user", "message": {"content": "hello"}}), encoding="utf-8")
    hooks.stop({"transcript_path": str(empty), "session_id": "s1", "cwd": str(root)}, env["cfg"])
    assert "Last session here" not in hooks.session_start({"cwd": str(root), "session_id": "s2"}, env["cfg"])
    hooks.stop({"transcript_path": _transcript(env["tmp"], root), "session_id": "s3", "cwd": str(env["tmp"] / "elsewhere")}, env["cfg"])
    assert not env["store"].db.execute("SELECT 1 FROM kv WHERE key LIKE 'handoff:%'").fetchone()


def test_handoff_keeps_project_files_and_real_errors_only(env, monkeypatch):
    root = _project(env, monkeypatch)
    env["cfg"].consolidate = False
    rows = [
        {"type": "user", "message": {"content": "refactor the cart"}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Write", "input": {"file_path": str(env["tmp"] / "scratch.py")}}]}},
        {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": "Edit", "input": {"file_path": str(root / "cart.ts")}}]}},
        {"type": "user", "message": {"content": [{"type": "tool_result", "is_error": True,
                                                  "content": "Permission for this command was denied by the user."}]}},
    ]
    t = env["tmp"] / "p.jsonl"; t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    hooks.stop({"transcript_path": str(t), "session_id": "s1", "cwd": str(root)}, env["cfg"])
    line = hooks.handoff_line(env["store"], "shop", "s2")
    assert "cart.ts" in line and "scratch.py" not in line and "error" not in line and not line.endswith("..")
