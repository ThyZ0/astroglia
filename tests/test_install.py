"""install/uninstall only touch NEXUS's own entries and keep the user's settings intact."""
import json

from nexus import cli


def test_install_then_uninstall_restores_settings(env, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)  # never touch the real `claude mcp` config
    s = env["claude"] / "settings.json"
    original = json.loads(s.read_text(encoding="utf-8"))
    original["hooks"] = {"SessionStart": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}]}
    s.write_text(json.dumps(original), encoding="utf-8")

    assert cli.main(["--home", str(env["cfg"].home), "install", "--yes"]) == 0
    installed = json.loads(s.read_text(encoding="utf-8"))
    cmds = [h["command"] for g in installed["hooks"]["SessionStart"] for h in g["hooks"]]
    assert "echo user-hook" in cmds and any("-m nexus hook session-start" in c for c in cmds)
    assert list((env["cfg"].home / "backups").glob("settings-*.json"))

    assert cli.main(["--home", str(env["cfg"].home), "install", "--yes"]) == 0  # idempotent
    again = json.loads(s.read_text(encoding="utf-8"))
    assert sum("-m nexus hook" in h["command"] for g in again["hooks"]["SessionStart"] for h in g["hooks"]) == 1

    assert cli.main(["--home", str(env["cfg"].home), "uninstall"]) == 0
    assert json.loads(s.read_text(encoding="utf-8")) == original
