"""Load benchmark on synthetic stores (temporary databases; never the user's).

    python bench/load.py [sizes...]      default: 1000 5000 20000

Measures, per size: routing latency (median of 20 tasks), freshness verification of 500 file-backed entries
(cold = hashing every file, warm = hash cache hit), and building the UI graph payload.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from astroglia import config, experiences, router, web  # noqa: E402
from astroglia.store import Store, now  # noqa: E402

WORDS = ("sync cache index graph route parser token budget schema migration deploy review test flaky socket auth "
         "billing invoice upload image queue worker retry backoff lock flush timeout render canvas layout hook").split()


def populate(store: Store, n: int, files_dir: Path, file_backed: int = 500) -> None:
    rnd = random.Random(n)
    ts = now()
    store.db.execute("BEGIN")
    for i in range(n):
        kind = ("skill", "experience", "decision", "knowledge", "project")[i % 5]
        title = " ".join(rnd.sample(WORDS, 3)) + f" {i}"
        summary = " ".join(rnd.sample(WORDS, 12))
        store.db.execute("INSERT INTO nodes(id, kind, title, summary, source, project, created, updated, verified) "
                         "VALUES(?,?,?,?,?,?,?,?,?)", (f"{kind}:{i}", kind, title, summary, "bench", f"p{i % 40}", ts, ts, ts))
        store.db.execute("INSERT INTO nodes_fts(id, title, summary, tags, body) VALUES(?,?,?,?,?)", (f"{kind}:{i}", title, summary, "", ""))
    for i in range(n * 2):
        a, b = rnd.randrange(n), rnd.randrange(n)
        ka, kb = ("skill", "experience", "decision", "knowledge", "project")[a % 5], ("skill", "experience", "decision", "knowledge", "project")[b % 5]
        store.db.execute("INSERT OR IGNORE INTO edges(src,dst,type,source,confidence,created,verified) VALUES(?,?,?,?,?,?,?)",
                         (f"{ka}:{a}", f"{kb}:{b}", "related_to", "bench", 0.7, ts, ts))
    store.db.commit()
    files_dir.mkdir(exist_ok=True)
    for i in range(file_backed):  # entries tied to real files (64 KB each) so verification has work to do
        f = files_dir / f"src{i}.py"
        f.write_bytes(bytes(rnd.getrandbits(8) for _ in range(256)) * 256)
        experiences.remember(store, f"file fact {i}", "fact about " + " ".join(rnd.sample(WORDS, 4)), files=[str(f)])


def run(sizes: list[int]) -> list[dict]:
    out = []
    for n in sizes:
        with tempfile.TemporaryDirectory() as tmp:
            cfg = config.load(tmp)
            store = Store(cfg.db_path)
            t0 = time.perf_counter()
            populate(store, n, Path(tmp) / "files")
            build_s = time.perf_counter() - t0
            tasks = [" ".join(random.Random(i).sample(WORDS, 4)) for i in range(20)]
            lat = []
            for t in tasks:
                t0 = time.perf_counter(); router.route(store, cfg, t, log=False); lat.append((time.perf_counter() - t0) * 1000)
            store.db.execute("DELETE FROM file_cache"); store.db.commit()
            t0 = time.perf_counter(); experiences.verify_all(store); cold = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter(); experiences.verify_all(store); warm = (time.perf_counter() - t0) * 1000
            t0 = time.perf_counter(); g = web.graph(store); graph_ms = (time.perf_counter() - t0) * 1000
            payload_kb = len(json.dumps(g)) / 1024
            store.close()
            out.append({"entries": n + 500, "edges": n * 2, "route_ms_p50": round(statistics.median(lat), 1),
                        "route_ms_max": round(max(lat), 1), "verify_500_files_cold_ms": round(cold),
                        "verify_500_files_cached_ms": round(warm), "graph_payload_ms": round(graph_ms),
                        "graph_payload_kb": round(payload_kb), "populate_s": round(build_s, 1)})
            print(json.dumps(out[-1]), flush=True)
    return out


if __name__ == "__main__":
    run([int(x) for x in sys.argv[1:]] or [1000, 5000, 20000])
