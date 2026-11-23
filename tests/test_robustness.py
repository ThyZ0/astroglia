"""Failure modes a user can hit, and behaviour at scale."""
import socket
import sqlite3
import time

import pytest

from astroglia import cli, experiences, router
from astroglia.store import SCHEMA_VERSION, Store


def test_database_from_newer_version_is_refused_clearly(tmp_path):
    db = tmp_path / "n.db"
    sqlite3.connect(db).execute(f"PRAGMA user_version={SCHEMA_VERSION + 1}")
    with pytest.raises(RuntimeError, match="newer than this Astroglia"):
        Store(db)


def test_broken_config_gives_a_message_not_a_traceback(env, capsys):
    (env["cfg"].home / "config.toml").write_text("project_roots = [unclosed", encoding="utf-8")
    assert cli.main(["--home", str(env["cfg"].home), "status"]) == 1
    assert "config.toml" in capsys.readouterr().out


def test_ui_on_busy_port_gives_a_message(env, capsys):
    s = socket.socket(); s.bind(("127.0.0.1", 0)); s.listen(); port = s.getsockname()[1]
    try:
        assert cli.main(["--home", str(env["cfg"].home), "ui", "--port", str(port), "--no-browser"]) == 1
        assert "already in use" in capsys.readouterr().out
    finally:
        s.close()


def test_uninstall_backs_up_settings_even_on_first_use(env, monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda _: None)
    cli.main(["--home", str(env["cfg"].home), "install", "--yes"])
    for f in (env["cfg"].home / "backups").glob("*"):
        f.unlink()
    (env["cfg"].home / "backups").rmdir()
    cli.main(["--home", str(env["cfg"].home), "uninstall"])
    assert list((env["cfg"].home / "backups").glob("settings-pre-uninstall-*.json"))


def test_routing_stays_fast_with_5000_entries(env):
    s = env["store"]
    words = "sync cache index graph route parser token budget schema migration deploy review test flaky socket".split()
    s.db.execute("BEGIN")
    for i in range(5000):
        title = f"{words[i % len(words)]} {words[(i * 7) % len(words)]} note {i}"
        s.db.execute("INSERT INTO nodes(id, kind, title, summary, source, created, updated, verified) VALUES(?,?,?,?,?,?,?,?)",
                     (f"knowledge:bulk{i}", "knowledge", title, title + " details", "test", "2026-01-01T00:00:00+00:00",
                      "2026-01-01T00:00:00+00:00", "2026-01-01T00:00:00+00:00"))
        s.db.execute("INSERT INTO nodes_fts(id, title, summary, tags, body) VALUES(?,?,?,?,?)", (f"knowledge:bulk{i}", title, title, "", ""))
    s.db.commit()
    experiences.remember(s, "Flaky socket test fix", "Await the server ready event before connecting")
    t0 = time.perf_counter()
    r = router.route(s, env["cfg"], "flaky socket test")
    elapsed = time.perf_counter() - t0
    assert r["selected"][0]["title"] == "Flaky socket test fix"
    assert elapsed < 2.0, f"route took {elapsed:.3f}s on 5000 entries"  # generous: shared CI runners are slow
