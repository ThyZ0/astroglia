"""Routing learns from what Claude really used, read from the transcript at turn end (never from a hook on
the tools themselves, so other MCP servers are not slowed down)."""
import json

from astroglia import hooks, router


def _caps(s):
    for sid, kind, title, summary in (
            ("mcp_server:user:shotter", "mcp_server", "shotter", "Drive a web page and capture images of it."),
            ("skill:user:pixels", "skill", "pixels", "Capture images of the desktop."),
            ("skill:acme@acme:audit", "skill", "audit", "Audit a code base.")):
        s.upsert({"id": sid, "kind": kind, "title": title, "summary": summary, "source": "scan:claude-code"})


def _transcript(tmp, rows):
    t = tmp / "t.jsonl"
    t.write_text("\n".join(json.dumps(r) for r in rows), encoding="utf-8")
    return str(t)


def _use(name, **inp):
    return {"type": "assistant", "message": {"content": [{"type": "tool_use", "name": name, "input": inp}]}}


def _say(text):
    return {"type": "user", "message": {"role": "user", "content": text}}


def test_used_capabilities_are_learned_once_and_rank_higher_for_similar_requests(env):
    s = env["store"]
    _caps(s)
    task = "capture images of the landing page"
    before = [x["id"] for x in router.route(s, env["cfg"], task, log=False)["selected"]]
    rows = [_say("<task-notification>ignored</task-notification>"), _say("capture images of the landing page please"),
            _use("mcp__shotter__navigate", url="x"), _use("mcp__shotter__screenshot"), _use("mcp__astroglia__route", task="x"),
            _say("now audit the code"), _use("Skill", skill="acme:audit")]
    t = _transcript(env["tmp"], rows)
    assert hooks.capability_uses(t) == [("capture images of the landing page please", "mcp_server", "shotter"),
                                        ("now audit the code", "skill", "acme:audit")]
    for _ in range(3):  # the Stop hook runs at every turn end: each use counts once
        hooks.learn_uses(s, t, "sess-1")
    learned = [e for e in s.events(50, kind="feedback") if e["payload"].get("implicit")]
    assert sorted(i for e in learned for i in e["payload"]["ids"]) == ["mcp_server:user:shotter", "skill:acme@acme:audit"]
    after = [x["id"] for x in router.route(s, env["cfg"], task, log=False)["selected"]]
    assert after.index("mcp_server:user:shotter") <= before.index("mcp_server:user:shotter")
    assert router.contextual_success(s, task, {"mcp_server:user:shotter"})["mcp_server:user:shotter"] > 0.5


def test_unknown_or_ambiguous_names_are_not_guessed(env):
    s = env["store"]
    _caps(s)
    s.upsert({"id": "skill:other@other:audit", "kind": "skill", "title": "audit", "summary": "x", "source": "scan:claude-code"})
    assert hooks.resolve_capability(s, "skill", "audit") is None            # two skills named audit
    assert hooks.resolve_capability(s, "skill", "acme:audit") == "skill:acme@acme:audit"
    assert hooks.resolve_capability(s, "mcp_server", "nowhere") is None
