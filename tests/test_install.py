"""install/uninstall only touch Astroglia's own entries and keep the user's settings intact."""
import json

from astroglia import cli


def test_install_then_uninstall_restores_settings(env, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)  # never touch the real `claude mcp` config
    s = env["claude"] / "settings.json"
    original = json.loads(s.read_text(encoding="utf-8"))
    original["hooks"] = {"SessionStart": [{"hooks": [{"type": "command", "command": "echo user-hook"}]}]}
    s.write_text(json.dumps(original), encoding="utf-8")

    assert cli.main(["--home", str(env["cfg"].home), "install", "--yes"]) == 0
    installed = json.loads(s.read_text(encoding="utf-8"))
    cmds = [h["command"] for g in installed["hooks"]["SessionStart"] for h in g["hooks"]]
    assert "echo user-hook" in cmds and any("-m astroglia hook session-start" in c for c in cmds)
    assert list((env["cfg"].home / "backups").glob("settings-*.json"))

    assert cli.main(["--home", str(env["cfg"].home), "install", "--yes"]) == 0  # idempotent
    again = json.loads(s.read_text(encoding="utf-8"))
    assert sum("-m astroglia hook" in h["command"] for g in again["hooks"]["SessionStart"] for h in g["hooks"]) == 1

    assert cli.main(["--home", str(env["cfg"].home), "uninstall"]) == 0
    assert json.loads(s.read_text(encoding="utf-8")) == original


def test_first_contact_is_readable_and_install_scans_right_away(env, monkeypatch, capsys):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    home = ["--home", str(env["cfg"].home)]
    assert cli.main(home) == 0
    out = capsys.readouterr().out
    assert "Not connected to Claude Code yet" in out and "astroglia install" in out
    assert cli.main(home + ["install"]) == 0
    assert "Dry run" in capsys.readouterr().out
    assert cli.main(home + ["install", "--yes"]) == 0
    out = capsys.readouterr().out
    assert "First scan" in out and "capabilities" in out and "Restart Claude Code" in out
    assert cli.main(home) == 0
    assert "Connected. Knows" in capsys.readouterr().out
    assert cli.main(home + ["--json", "status"]) == 0
    assert json.loads(capsys.readouterr().out)["nodes_by_kind"]          # --json keeps machine output
