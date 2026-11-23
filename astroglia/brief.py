"""Project brief: what an agent would otherwise rediscover at the start of every session.

Deterministic (no LLM): manifests (package.json, pyproject.toml, Cargo.toml, go.mod, ...), their scripts
and dependencies, languages, top-level layout, likely entry points, tests, the README's opening and the
files that change most often in git. Every line comes from a file; the brief is tied to those files'
hashes, so it is flagged stale (and rebuilt at the next sync) when they change.
"""
from __future__ import annotations

import json
import re
import subprocess
import tomllib
from collections import Counter
from pathlib import Path

SKIP_DIRS = {".git", "node_modules", ".venv", "venv", "env", "__pycache__", "dist", "build", "target", ".next",
             ".nuxt", "out", "coverage", ".cache", ".idea", ".vscode", "vendor", ".gradle", "bin", "obj", ".astroglia"}
LANG = {".py": "Python", ".ts": "TypeScript", ".tsx": "TypeScript", ".js": "JavaScript", ".jsx": "JavaScript",
        ".mjs": "JavaScript", ".rs": "Rust", ".go": "Go", ".java": "Java", ".kt": "Kotlin", ".cs": "C#", ".cpp": "C++",
        ".c": "C", ".h": "C/C++", ".rb": "Ruby", ".php": "PHP", ".swift": "Swift", ".vue": "Vue", ".svelte": "Svelte",
        ".sql": "SQL", ".sh": "Shell", ".ps1": "PowerShell", ".dart": "Dart", ".lua": "Lua", ".tex": "LaTeX", ".ipynb": "Notebook"}
MANIFESTS = ("package.json", "pyproject.toml", "requirements.txt", "Cargo.toml", "go.mod", "pom.xml", "build.gradle",
             "build.gradle.kts", "composer.json", "Gemfile", "Makefile", "docker-compose.yml", "Dockerfile")
ENTRY_CANDIDATES = ("main.py", "app.py", "manage.py", "__main__.py", "src/main.py", "src/index.ts", "src/index.js", "src/main.ts",
                    "src/main.tsx", "src/App.tsx", "index.js", "server.js", "app/page.tsx", "app/layout.tsx", "pages/index.tsx",
                    "src/main.rs", "src/lib.rs", "main.go", "cmd/main.go", "Program.cs")
FRAMEWORKS = ("next", "react", "vue", "svelte", "@angular/core", "express", "fastify", "vite", "electron", "tailwindcss",
              "prisma", "drizzle-orm", "django", "flask", "fastapi", "pytest", "torch", "numpy", "pandas", "tokio", "actix-web",
              "axum", "serde", "spring-boot", "jest", "vitest", "playwright")
MAX_FILES = 20000


def _read(p: Path, limit: int = 200_000) -> str:
    try:
        return p.read_text(encoding="utf-8", errors="replace")[:limit]
    except OSError:
        return ""


def _walk(root: Path):
    stack, n = [root], 0
    while stack and n < MAX_FILES:
        d = stack.pop()
        try:
            entries = list(d.iterdir())
        except OSError:
            continue
        for e in entries:
            if e.is_dir():
                if e.name not in SKIP_DIRS and not e.name.startswith("."):
                    stack.append(e)
            else:
                n += 1
                yield e


def _git(root: Path, *args: str) -> str:
    try:
        r = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=10)
        return r.stdout if r.returncode == 0 else ""
    except (OSError, subprocess.SubprocessError):
        return ""


def build(root: Path) -> dict | None:
    """Return {"summary", "body", "files", "bytes_summarized"} or None if nothing useful was found."""
    root = Path(root)
    lines, stack, commands, sources = [], [], [], []
    langs, top = Counter(), Counter()
    for f in _walk(root):
        if f.suffix.lower() in LANG:
            langs[LANG[f.suffix.lower()]] += 1
        rel = f.relative_to(root).parts
        top[rel[0] + ("/" if len(rel) > 1 else "")] += 1

    for name in MANIFESTS:
        for p in [root / name, *[c / name for c in root.iterdir() if c.is_dir() and c.name not in SKIP_DIRS
                                 and not c.name.startswith(".")]] if root.is_dir() else []:
            if p.exists():
                sources.append(p)
    for p in sources:
        rel = p.relative_to(root).as_posix()
        text = _read(p)
        if p.name == "package.json":
            try:
                d = json.loads(text)
            except ValueError:
                continue
            deps = {**d.get("dependencies", {}), **d.get("devDependencies", {})}
            fw = [k for k in FRAMEWORKS if k in deps]
            lines.append(f"- `{rel}`: {d.get('name', '?')} · {len(deps)} deps" + (f" ({', '.join(fw)})" if fw else ""))
            stack += fw
            for k in ("dev", "build", "test", "lint", "start", "typecheck"):
                if k in d.get("scripts", {}):
                    commands.append(f"`npm run {k}` ({rel.rsplit('/', 1)[0] if '/' in rel else '.'}): {d['scripts'][k][:80]}")
        elif p.name == "pyproject.toml":
            try:
                d = tomllib.loads(text)
            except ValueError:
                continue
            proj = d.get("project", {})
            deps = [re.split(r"[<>=!~\[; ]", x)[0] for x in proj.get("dependencies", [])]
            lines.append(f"- `{rel}`: {proj.get('name', '?')} · Python {proj.get('requires-python', '?')} · deps: {', '.join(deps[:10]) or 'none'}")
            stack += [x for x in deps if x in FRAMEWORKS]
            for k, v in proj.get("scripts", {}).items():
                commands.append(f"`{k}` (console script → {v})")
            if "pytest" in text or (root / "tests").is_dir():
                commands.append("`python -m pytest`")
        elif p.name == "Cargo.toml":
            try:
                d = tomllib.loads(text)
            except ValueError:
                continue
            deps = list(d.get("dependencies", {}))
            lines.append(f"- `{rel}`: {d.get('package', {}).get('name', 'workspace')} · deps: {', '.join(deps[:10]) or 'none'}")
            commands += ["`cargo build`", "`cargo test`"]
        elif p.name == "go.mod":
            m = re.search(r"^module\s+(\S+)", text, re.M)
            lines.append(f"- `{rel}`: Go module {m.group(1) if m else '?'}")
            commands.append("`go test ./...`")
        elif p.name == "Makefile":
            targets = re.findall(r"^([a-zA-Z][\w-]*):", text, re.M)[:8]
            lines.append(f"- `{rel}`: make targets {', '.join(targets)}")
        else:
            lines.append(f"- `{rel}`")

    readme = next((root / n for n in ("README.md", "README.rst", "README.txt", "readme.md") if (root / n).exists()), None)
    lede = ""
    if readme:
        sources.append(readme)
        paras = [p.strip() for p in re.split(r"\n\s*\n", _read(readme, 20000)) if p.strip() and not p.strip().startswith(("#", "!", "[!", "<", "```", "|", "---"))]
        lede = re.sub(r"\s+", " ", paras[0])[:400] if paras else ""
    claude_md = root / "CLAUDE.md"
    # look next to every manifest too: many repos keep the app in a subfolder (e.g. web/, app/)
    bases = list(dict.fromkeys([root, *[p.parent for p in sources if p.name in MANIFESTS]]))
    entries = [(b / e).relative_to(root).as_posix() for b in bases for e in ENTRY_CANDIDATES if (b / e).exists()]
    tests = sorted({d.relative_to(root).as_posix() for b in bases for d in b.iterdir()
                    if d.is_dir() and d.name in ("tests", "test", "__tests__", "spec", "e2e")})

    if not (lines or langs or lede):
        return None
    hot = Counter(l for l in _git(root, "log", "-n", "200", "--name-only", "--pretty=format:").splitlines() if l.strip())
    last = _git(root, "log", "-1", "--pretty=format:%h %cs %s").strip()
    branch = _git(root, "rev-parse", "--abbrev-ref", "HEAD").strip()

    lang_txt = ", ".join(f"{k} ({v})" for k, v in langs.most_common(5))
    body = [f"# Project brief: {root.name}", "", "Generated by Astroglia from the files listed under Sources. Facts, not guesses.", ""]
    if lede:
        body += ["## What it is", lede, ""]
    body += ["## Stack", f"Languages (files): {lang_txt or 'unknown'}"]
    if stack:
        body.append("Frameworks/libraries: " + ", ".join(dict.fromkeys(stack)))
    body += [""] + (["## Manifests", *lines, ""] if lines else [])
    if commands:
        body += ["## Commands", *[f"- {c}" for c in dict.fromkeys(commands)], ""]
    if entries:
        body += ["## Likely entry points", *[f"- `{e}`" for e in entries], ""]
    if tests:
        body += ["## Tests", *[f"- `{t}/`" for t in tests], ""]
    body += ["## Layout (files per top-level entry)", *[f"- `{k}` {v}" for k, v in top.most_common(12)], ""]
    if hot:
        body += ["## Most changed files (last 200 commits)", *[f"- `{k}` ({v})" for k, v in hot.most_common(8)], ""]
    if last:
        body += [f"Git: branch `{branch}`, last commit {last}", ""]
    if claude_md.exists():
        body += ["Project rules: see `CLAUDE.md` (read it; it is not summarised here).", ""]
    body += ["## Sources", *[f"- `{p.relative_to(root).as_posix()}`" for p in sources]]

    summary = f"{lang_txt or 'unknown languages'}"
    if stack:
        summary += f" · {', '.join(list(dict.fromkeys(stack))[:6])}"
    if commands:
        summary += f" · commands: {'; '.join(c.split(' (')[0] for c in list(dict.fromkeys(commands))[:4])}"
    if lede:
        summary += f" · {lede[:160]}"
    return {"summary": summary, "body": "\n".join(body), "files": [str(p) for p in sources],
            "bytes_summarized": sum(p.stat().st_size for p in sources)}
