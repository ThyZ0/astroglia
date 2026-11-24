"""Optional meaning-based matching for routing.

Keyword search cannot link "am I free on thursday" to a calendar tool: they share no word. A small static
embedding model (model2vec, potion-base-8M, about 30 MB) compares meanings locally in ~0.1 ms per task.
Off by default: `pip install "astroglia[semantic]"`, then `astroglia semantic --enable` downloads the model
once into ~/.astroglia/models. After that it is read from disk only: no network, no LLM call.
Any failure falls back to keyword-only routing. ASTROGLIA_SEMANTIC=0 turns it off (used to measure it).
"""
from __future__ import annotations

import os
import re
import shutil

from .text import FR_EN, STOP, fold, positive

MODEL = "minishlab/potion-base-8M"
CAP_KINDS = ("plugin", "skill", "command", "agent", "mcp_server", "hook")
_model = None
_failed = False
_vecs: dict[str, tuple[str, object]] = {}  # id -> (updated, unit vector); shortcut: in-process only, persist if CLI latency matters at 20k


def model_dir(cfg):
    return cfg.home / "models" / MODEL.split("/")[-1]


def enabled(cfg) -> bool:
    return os.environ.get("ASTROGLIA_SEMANTIC", "1") != "0" and model_dir(cfg).exists()


def _load(cfg):
    global _model, _failed
    if _model is None and not _failed:
        try:
            from model2vec import StaticModel
            _model = StaticModel.from_pretrained(str(model_dir(cfg)))
        except Exception:  # missing package or damaged files: keyword-only routing
            _failed = True
    return _model


def enable(cfg) -> dict:
    try:
        from model2vec import StaticModel
    except ImportError:
        return {"enabled": False, "error": 'model2vec is not installed. Run: pip install "astroglia[semantic]"'}
    m = StaticModel.from_pretrained(MODEL)  # the one network access: downloads the public model
    model_dir(cfg).parent.mkdir(parents=True, exist_ok=True)
    m.save_pretrained(str(model_dir(cfg)))
    return {"enabled": True, "model": MODEL, "path": str(model_dir(cfg))}


def disable(cfg) -> dict:
    shutil.rmtree(model_dir(cfg), ignore_errors=True)
    return {"enabled": False, "removed": str(model_dir(cfg))}


def doc_text(n: dict) -> str:
    if n["kind"] in CAP_KINDS:  # what a capability is for, without its "not for ..." sentences
        body = "" if n["kind"] == "mcp_server" else positive(n["body"] or "")[:1500]  # a long tool list resembles every task
        return f"{n['title']}. {positive(n['summary'])} {body}"
    return f"{n['title']}. {n['summary']} {(n['body'] or '')[:1500]}"


def query_text(task: str) -> str:
    """The task's meaningful words with the English gloss of French ones. The model is English: given a raw
    French sentence it matches French descriptions by language rather than by meaning."""
    words = [w for w in re.findall(r"[a-z0-9]+", fold(task)) if len(w) > 1 and w not in STOP]
    return " ".join(FR_EN.get(w, w) for w in words)  # replace, not append: leftover French pulls French texts


_index: dict = {"key": None}  # all entries' vectors as one matrix, rebuilt only when the store changes


def _matrix(m, store):
    import numpy as np
    key = (str(store.path), *store.db.execute("SELECT COUNT(*), MAX(updated) FROM nodes").fetchone())
    if _index["key"] != key:
        nodes = store.nodes()
        todo = [n for n in nodes if _vecs.get(n["id"], ("",))[0] != n["updated"]]
        if todo:
            V = m.encode([doc_text(n) for n in todo])
            V = V / (np.linalg.norm(V, axis=1, keepdims=True) + 1e-9)
            for n, v in zip(todo, V):
                _vecs[n["id"]] = (n["updated"], v)
        _index.update(key=key, nodes=[(n["id"], n["kind"], n["status"]) for n in nodes],
                      M=np.stack([_vecs[n["id"]][1] for n in nodes]) if nodes else None)
    return _index


def similarities(cfg, store, task: str, keep) -> dict[str, float] | None:
    """Cosine similarity of the task to every entry for which keep(kind, status) is true,
    or None when semantic matching is off or unavailable."""
    if not enabled(cfg):
        return None
    m = _load(cfg)
    if m is None:
        return None
    try:
        import numpy as np
        ix = _matrix(m, store)
        if ix["M"] is None:
            return None
        q = m.encode([query_text(task)])[0]
        sc = ix["M"] @ (q / (np.linalg.norm(q) + 1e-9))
        return {nid: float(sc[i]) for i, (nid, kind, status) in enumerate(ix["nodes"]) if keep(kind, status)}
    except Exception:
        return None
