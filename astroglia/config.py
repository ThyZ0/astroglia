"""Paths and tunables. Optional overrides in $ASTROGLIA_HOME/config.toml."""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

DEFAULT_WEIGHTS = {
    "relevance": 0.55,   # lexical match with the task (BM25, normalized)
    "named": 0.25,       # the task names the resource itself
    "confidence": 0.15,  # how much we trust the entry
    "freshness": 0.10,   # decays with time since last verification
    "success": 0.10,     # observed usefulness (feedback)
    "project": 0.10,     # belongs to the project being worked on
}


@dataclass
class Config:
    home: Path
    claude_dir: Path
    claude_json: Path
    weights: dict = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))
    redundancy_threshold: float = 0.35
    min_score: float = 0.25
    half_life_days: float = 90.0
    max_per_kind: int = 3
    project_roots: list[str] = field(default_factory=list)

    @property
    def db_path(self) -> Path:
        return self.home / "astroglia.db"


def load(home: str | os.PathLike | None = None) -> Config:
    h = Path(home or os.environ.get("ASTROGLIA_HOME") or Path.home() / ".astroglia")
    claude_dir = Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude")
    cfg = Config(home=h, claude_dir=claude_dir, claude_json=Path.home() / ".claude.json")
    f = h / "config.toml"
    if f.exists():
        data = tomllib.loads(f.read_text(encoding="utf-8"))
        for key in ("redundancy_threshold", "min_score", "half_life_days", "max_per_kind", "project_roots"):
            if key in data:
                setattr(cfg, key, data[key])
        for key in ("claude_dir", "claude_json"):
            if key in data:
                setattr(cfg, key, Path(data[key]))
        cfg.weights.update(data.get("weights", {}))
    return cfg
