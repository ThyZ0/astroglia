"""Providers (projects, Graphify, Cortex, Claude Code memory) and scenarios 1-2 (project understanding)."""
import json

from astroglia import experiences, providers, router
from astroglia.store import Store

from conftest import write


def make_repo(root, head="a" * 40, built="a" * 40):
    write(root / ".git" / "HEAD", "ref: refs/heads/main\n")
    write(root / ".git" / "refs" / "heads" / "main", head + "\n")
    graph = {"nodes": [{"id": "n1", "community_name": "Route optimizer"}, {"id": "n2", "community_name": "Billing"}],
             "links": [{"source": "n1", "target": "n2"}], "built_at_commit": built}
    write(root / "graphify-out" / "graph.json", json.dumps(graph))
    write(root / "CLAUDE.md", "# Planner\nRules: use pnpm. Never commit .env files.\n")
    write(root / "src" / "routes.py", "def optimise(): ...\n")
    write(root / "src" / "billing.py", "def invoice(): ...\n")
    return root


def setup(env, monkeypatch, **repo):
    monkeypatch.setattr(providers, "cortex_projects", lambda: [])
    root = make_repo(env["tmp"] / "planner", **repo)
    env["cfg"].project_roots = [str(root)]
    return root


def test_project_card_points_to_graphify_and_detects_stale_graph(env, monkeypatch):
    setup(env, monkeypatch, head="b" * 40, built="a" * 40)
    providers.sync(env["store"], env["cfg"])
    p = env["store"].get("project:planner")
    assert p["meta"]["providers"]["graphify"]["stale"] is True
    assert "STALE" in p["summary"] and "graphify query" in p["summary"]
    assert "Route optimizer" in p["tags"]
    claude_md = env["store"].get("knowledge:claude-md:planner")
    assert claude_md["ref"].endswith("CLAUDE.md") and claude_md["body"] is None  # pointer, not a copy
    r = router.route(env["store"], env["cfg"], "improve the route optimizer", kinds=["project"])
    assert r["selected"][0]["id"] == "project:planner"


def test_cortex_projects_are_named_by_cortex(env, monkeypatch):
    root = setup(env, monkeypatch)
    monkeypatch.setattr(providers, "cortex_projects", lambda: [
        {"name": "Planner", "files": 3, "symbols": 9, "root": str(root), "languages": ["python"]}])
    providers.sync(env["store"], env["cfg"])
    p = env["store"].get("project:Planner")
    assert "cortex_pack" in p["summary"] and p["meta"]["providers"]["cortex"]["symbols"] == 9


def test_claude_code_memory_files_are_indexed_as_pointers(env, monkeypatch):
    setup(env, monkeypatch)
    write(env["claude"] / "projects" / "C--x" / "memory" / "db-choice.md",
          "---\nname: db-choice\ndescription: Team chose Postgres over Mongo for billing\nmetadata:\n  type: project\n---\nbody\n")
    write(env["claude"] / "projects" / "C--x" / "memory" / "MEMORY.md", "- index")
    rep = providers.sync(env["store"], env["cfg"])
    assert rep["cc_memory"]["created"] == ["knowledge:cc-memory:C--x/db-choice"]
    r = router.route(env["store"], env["cfg"], "why did we choose postgres for billing?")
    assert r["selected"][0]["id"] == "knowledge:cc-memory:C--x/db-choice"


def test_scenario1_project_understanding_reused_across_sessions(env, monkeypatch):
    root = setup(env, monkeypatch)
    providers.sync(env["store"], env["cfg"])
    card = providers.project_card(env["store"], "planner")
    assert [e["id"] for e in card["entries"]["active"]] == ["knowledge:brief:planner"]  # automatic, before any analysis
    # First session: the agent analyses the project once, one entry per aspect, each tied to its files.
    experiences.remember(env["store"], "Planner architecture", "Two modules: routes (optimiser) and billing.",
                         kind="knowledge", project="planner", files=[str(root / "src" / "routes.py"), str(root / "src" / "billing.py")])
    experiences.remember(env["store"], "Route optimiser", "optimise() in src/routes.py does greedy TSP.",
                         kind="knowledge", project="planner", files=[str(root / "src" / "routes.py")])
    experiences.remember(env["store"], "Billing", "invoice() in src/billing.py builds PDF invoices.",
                         kind="knowledge", project="planner", files=[str(root / "src" / "billing.py")])
    env["store"].close()
    # New session: fresh connection, nothing re-analysed, everything still valid.
    env["store"] = Store(env["cfg"].db_path)
    card = providers.project_card(env["store"], str(root / "src"))  # a path inside the project works too
    assert card["project"]["id"] == "project:planner"
    assert len(card["entries"]["active"]) == 4 and card["entries"]["stale"] == []  # 3 remembered + the brief
    assert "no re-analysis needed" in card["advice"]


def test_scenario2_changed_file_invalidates_only_dependent_entries(env, monkeypatch):
    root = setup(env, monkeypatch)
    providers.sync(env["store"], env["cfg"])
    for title, files in (("Architecture", ["routes.py", "billing.py"]), ("Routes", ["routes.py"]), ("Billing", ["billing.py"])):
        experiences.remember(env["store"], title, f"{title} notes", kind="knowledge", project="planner",
                             files=[str(root / "src" / f) for f in files])
    (root / "src" / "billing.py").write_text("def invoice(vat): ...\n", encoding="utf-8")
    card = providers.project_card(env["store"], "planner")
    assert sorted(e["title"] for e in card["entries"]["stale"]) == ["Architecture", "Billing"]
    assert sorted(e["title"] for e in card["entries"]["active"]) == ["Routes", "planner: project brief"]
    assert card["changed_files"] == [str((root / "src" / "billing.py").resolve())]
    assert "Re-check only the stale ones (1 changed files)" in card["advice"]


def test_vanished_project_is_flagged_not_deleted(env, monkeypatch):
    import shutil
    root = setup(env, monkeypatch)
    providers.sync(env["store"], env["cfg"])
    shutil.rmtree(root)
    rep = providers.sync(env["store"], env["cfg"])
    assert "project:planner" in rep["projects"]["missing"]
    assert env["store"].get("project:planner")["status"] == "missing"


def test_same_folder_name_in_two_places_gives_two_projects(env, monkeypatch):
    first = setup(env, monkeypatch)
    providers.sync(env["store"], env["cfg"])
    other = make_repo(env["tmp"] / "elsewhere" / "planner")
    env["cfg"].project_roots = [str(other), str(first)]  # order must not rename the existing project
    providers.sync(env["store"], env["cfg"])
    assert env["store"].get("project:planner")["meta"]["root"] == str(first)
    assert env["store"].get("project:elsewhere/planner")["meta"]["root"] == str(other)


def test_brief_is_built_from_manifests_and_rebuilt_only_when_they_change(env, monkeypatch):
    root = setup(env, monkeypatch)
    write(root / "package.json", json.dumps({"name": "planner-web", "scripts": {"dev": "vite", "test": "vitest run"},
                                              "dependencies": {"react": "19", "vite": "6"}}))
    write(root / "README.md", "# Planner\n\nSchedules ambulance rounds and optimises routes for medical transport.\n")
    rep = providers.sync(env["store"], env["cfg"])
    assert rep["briefs"]["built"] == ["knowledge:brief:planner"]
    b = env["store"].get("knowledge:brief:planner")
    assert "react" in b["summary"] and "npm run test" in b["body"] and "ambulance" in b["body"]
    assert "src/" in b["body"] and b["meta"]["bytes_summarized"] > 0
    assert providers.sync(env["store"], env["cfg"])["briefs"]["built"] == []  # nothing changed: not rebuilt
    write(root / "package.json", json.dumps({"name": "planner-web", "scripts": {"e2e": "playwright test"}, "dependencies": {}}))
    assert providers.sync(env["store"], env["cfg"])["briefs"]["built"] == ["knowledge:brief:planner"]
    assert "npm run test" not in env["store"].get("knowledge:brief:planner")["body"]


def test_session_start_puts_current_project_brief_in_manifest(env, monkeypatch):
    from astroglia import hooks
    root = setup(env, monkeypatch)
    write(root / "pyproject.toml", '[project]\nname = "planner"\nrequires-python = ">=3.11"\ndependencies = ["fastapi", "pytest"]\n')
    out = hooks.session_start({"cwd": str(root / "src")}, env["cfg"])
    assert "Project brief" in out and "fastapi" in out


def test_indexing_tools_are_bridged_to_the_projects_they_index(env, monkeypatch):
    root = setup(env, monkeypatch)
    env["store"].upsert({"id": "skill:x:graphify", "kind": "skill", "title": "graphify", "source": "scan:claude-code"})
    providers.sync(env["store"], env["cfg"])
    assert any(e["src"] == "skill:x:graphify" and e["type"] == "used_in" for e in env["store"].edges("project:planner"))


def test_project_at_picks_the_deepest_project(env, tmp_path):
    outer, inner = tmp_path / "work", tmp_path / "work" / "app"
    (inner / "src").mkdir(parents=True)
    for name, root in (("work", outer), ("app", inner)):
        env["store"].upsert({"id": f"project:{name}", "kind": "project", "title": name, "summary": name,
                             "source": "scan:projects", "meta": {"root": str(root)}})
    assert providers.project_at(env["store"], str(inner / "src"))["title"] == "app"
    assert providers.project_at(env["store"], str(outer))["title"] == "work"
    assert providers.project_at(env["store"], str(tmp_path / "elsewhere")) is None
