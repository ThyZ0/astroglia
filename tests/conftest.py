import json
from pathlib import Path

import pytest

from astroglia import config
from astroglia.store import Store


def write(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def skill(root: Path, name: str, desc: str) -> Path:
    return write(root / name / "SKILL.md", f"---\nname: {name}\ndescription: {json.dumps(desc)}\n---\n# {name}\n")


@pytest.fixture
def env(tmp_path, monkeypatch):
    """A fake Claude Code install + empty Astroglia home."""
    claude = tmp_path / "claude"
    plugin = tmp_path / "plugins" / "csvkit"
    write(plugin / ".claude-plugin" / "plugin.json", json.dumps({"name": "csvkit", "description": "CSV tools", "version": "1.0"}))
    skill(plugin / "skills", "csv-analyze", "Analyze CSV spreadsheet files: column statistics, missing values, data types and outliers in tabular data.")
    skill(plugin / "skills", "csv-profile", "Profile CSV spreadsheet files: column statistics, missing values, data types and outliers for tabular data.")
    write(plugin / "commands" / "csv-clean.md", "---\ndescription: Clean a CSV file\n---\nbody")
    write(plugin / "hooks" / "hooks.json", json.dumps({"hooks": {"SessionStart": [{"hooks": [{"type": "command", "command": "echo hi"}]}]}}))
    write(claude / "settings.json", json.dumps({"enabledPlugins": {"csvkit@local": True}}))
    write(claude / "plugins" / "installed_plugins.json",
          json.dumps({"plugins": {"csvkit@local": [{"installPath": str(plugin), "version": "1.0"}]}}))
    skill(claude / "skills", "python-review", "Review Python code for bugs, style and test coverage before merging.")
    cj = write(tmp_path / ".claude.json", json.dumps({"mcpServers": {"db": {"type": "stdio", "command": "dbserver",
                                                                           "env": {"DB_PASSWORD": "hunter2-secret"}}}}))
    from astroglia import providers
    monkeypatch.setattr(providers, "cortex_projects", lambda: [])  # never call the machine's real cortex
    home = tmp_path / "astroglia"
    monkeypatch.setenv("ASTROGLIA_HOME", str(home))
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(claude))
    cfg = config.load(home)
    cfg.claude_json = cj
    store = Store(cfg.db_path)
    yield {"cfg": cfg, "store": store, "claude": claude, "plugin": plugin, "tmp": tmp_path}
    store.close()
