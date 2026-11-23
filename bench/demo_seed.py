"""Build the demo dataset used for the README screenshots (fictional install, clearly not real usage).

    python bench/demo_seed.py <empty-dir>
    astroglia --home <empty-dir>/home ui

Creates a fake Claude Code configuration (generic skills, plugins, MCP servers), three sample projects
with real manifests, a few remembered experiences tied to files, then runs a normal sync, some routings
and feedback through the public API. Nothing here comes from a real user.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def w(p: Path, text: str) -> Path:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


def skill(root: Path, name: str, desc: str) -> None:
    w(root / name / "SKILL.md", f"---\nname: {name}\ndescription: {json.dumps(desc)}\n---\n# {name}\n")


def main(base: Path) -> None:
    claude, home, projects = base / "claude", base / "home", base / "projects"
    plugins = {
        "dev-workflow@demo": {"code-review": "Review a diff for correctness bugs before merging; reports findings ranked by severity.",
                              "test-driven-development": "Write the failing test first, then the minimum code; use when implementing a feature or fixing a bug.",
                              "systematic-debugging": "Find the root cause of a failing test or bug before proposing a fix; then lock it with test-driven-development.",
                              "writing-plans": "Turn a spec into a step-by-step implementation plan before touching code."},
        "documents@demo": {"pdf": "Read, fill, merge or split PDF files; extract tables and text.",
                           "xlsx": "Create or edit spreadsheets with formulas and charts.",
                           "pptx": "Build slide decks from an outline."},
        "frontend@demo": {"frontend-design": "Design and build polished web interfaces; layout, typography and accessibility.",
                          "browser-testing": "Drive a real browser to check a page works: click, fill forms, read console errors. Pairs with frontend-design."},
    }
    installed = {}
    for key, skills in plugins.items():
        root = base / "plugins" / key.split("@")[0]
        w(root / ".claude-plugin" / "plugin.json", json.dumps({"name": key.split("@")[0], "description": f"Demo plugin {key.split('@')[0]}", "version": "1.0.0"}))
        for name, desc in skills.items():
            skill(root / "skills", name, desc)
        installed[key] = [{"installPath": str(root), "version": "1.0.0"}]
    w(claude / "settings.json", json.dumps({"enabledPlugins": {k: True for k in plugins}}))
    w(claude / "plugins" / "installed_plugins.json", json.dumps({"plugins": installed}))
    skill(claude / "skills", "review-pr", "Review a pull request diff for bugs and missing tests before merge; lighter than code-review, no severity ranking.")
    skill(claude / "skills", "release-notes", "Write release notes from merged pull requests and the changelog.")
    cj = w(base / ".claude.json", json.dumps({"mcpServers": {
        "github": {"type": "http", "url": "https://api.githubcopilot.com/mcp/"},
        "postgres": {"type": "stdio", "command": "postgres-mcp", "env": {"DATABASE_URL": "never-stored"}},
        "docs-search": {"type": "stdio", "command": "docs-mcp"}}}))

    shop = projects / "acme-shop"
    w(shop / "package.json", json.dumps({"name": "acme-shop", "scripts": {"dev": "next dev", "build": "next build", "test": "vitest run", "lint": "eslint ."},
                                        "dependencies": {"next": "15", "react": "19", "drizzle-orm": "0.3", "tailwindcss": "4"}, "devDependencies": {"vitest": "3"}}))
    w(shop / "README.md", "# Acme Shop\n\nA small storefront: catalogue, cart and Stripe checkout, built with Next.js.\n")
    w(shop / "app" / "page.tsx", "export default function Page() { return null }\n")
    cart = w(shop / "lib" / "cart.ts", "export function total(items) { return items.reduce((s, i) => s + i.price * i.qty, 0) }\n")
    checkout = w(shop / "app" / "api" / "checkout" / "route.ts", "export async function POST() { /* stripe */ }\n")
    w(shop / "tests" / "cart.test.ts", "import { total } from '../lib/cart'\n")
    api = projects / "weather-api"
    w(api / "pyproject.toml", '[project]\nname = "weather-api"\nrequires-python = ">=3.11"\ndependencies = ["fastapi", "httpx", "pytest"]\n')
    w(api / "README.md", "# Weather API\n\nCaches forecasts from three providers and serves them over a FastAPI endpoint.\n")
    cache = w(api / "app" / "cache.py", "TTL = 600\n")
    w(api / "app" / "main.py", "from fastapi import FastAPI\napp = FastAPI()\n")
    w(api / "tests" / "test_cache.py", "def test_ttl(): pass\n")
    cli = projects / "log-crunch"
    w(cli / "Cargo.toml", '[package]\nname = "log-crunch"\n[dependencies]\nserde = "1"\ntokio = "1"\n')
    w(cli / "README.md", "# log-crunch\n\nFast log aggregation CLI written in Rust.\n")
    w(cli / "src" / "main.rs", "fn main() {}\n")
    w(home / "config.toml", "project_roots = [" + ", ".join(json.dumps(str(p).replace("\\", "/")) for p in (shop, api, cli)) + "]\n")

    os.environ["CLAUDE_CONFIG_DIR"] = str(claude)
    from astroglia import config, experiences, providers, router
    from astroglia.store import Store
    providers.cortex_projects = lambda: []  # never read the machine's real Cortex index into the demo
    cfg = config.load(home)
    cfg.claude_json = cj
    store = Store(cfg.db_path)
    providers.sync_all(store, cfg)
    experiences.remember(store, "Cart total drifted with discount codes", "Discounts were applied per line and again on the total; "
                         "fixed by applying them once in total().", kind="experience", project="acme-shop", files=[str(cart)])
    experiences.remember(store, "Checkout uses Stripe idempotency keys", "Every POST /api/checkout sends an idempotency key derived "
                         "from the cart id, so retries never double-charge.", kind="decision", project="acme-shop", files=[str(checkout)])
    experiences.remember(store, "Forecast cache TTL is 10 minutes", "Providers rate-limit at 60/h; a 600 s TTL keeps us under it "
                         "for 5 cities.", kind="decision", project="weather-api", files=[str(cache)])
    experiences.remember(store, "Flaky provider timeouts", "Provider B times out under load; wrap calls in httpx retries with "
                         "backoff (3 tries).", kind="experience", project="weather-api", files=[str(cache)])
    for task, proj in (("review the checkout pull request before merging", "acme-shop"), ("why does the cart total change with discounts", "acme-shop"),
                       ("a forecast test is failing intermittently", "weather-api"), ("fill the supplier PDF form", None)):
        r = router.route(store, cfg, task, project=proj)
        if r["selected"]:
            router.feedback(store, [r["selected"][0]["id"]], True)
    for p in ("acme-shop", "weather-api"):
        b = store.get(f"knowledge:brief:{p}")
        store.log("served", id=b["id"], kind="brief", via="wake", bytes=b["meta"]["bytes_summarized"])
    cache.write_text("TTL = 300\n", encoding="utf-8")  # one source changed: the TTL decision becomes stale
    experiences.verify_all(store)
    print(f"demo ready: astroglia --home {home} ui")


if __name__ == "__main__":
    main(Path(sys.argv[1]).resolve())
