"""Meaning-based routing is optional, local and fail-open. The real model is not needed: a fake encoder
maps words to a few concepts, so the tests check the routing logic, not the model's quality."""
import pytest

from astroglia import experiences, router, semantic

np = pytest.importorskip("numpy")

CONCEPTS = {"calendar": 0, "schedule": 0, "free": 0, "thursday": 0, "meeting": 0, "events": 0,
            "browser": 1, "website": 1, "screenshot": 1, "pdf": 2, "document": 2}


class FakeModel:
    def encode(self, texts):
        out = []
        for t in texts:
            v = np.full(4, 0.05)
            for w in t.lower().replace(".", " ").split():
                if w in CONCEPTS:
                    v[CONCEPTS[w]] += 1
            out.append(v)
        return np.array(out)


@pytest.fixture
def sem(env, monkeypatch):
    s = env["store"]
    s.upsert({"id": "skill:user:gcal", "kind": "skill", "title": "gcal", "summary": "List calendar events and schedule a meeting.",
              "source": "scan:claude-code"})
    s.upsert({"id": "skill:user:pdf", "kind": "skill", "title": "pdf", "summary": "Fill and merge pdf document forms.",
              "source": "scan:claude-code"})
    experiences.remember(s, "standup", "Weekly meeting notes about the calendar")  # memory, shares no word with the task
    monkeypatch.setattr(semantic, "_vecs", {})
    monkeypatch.setattr(semantic, "_index", {"key": None})
    monkeypatch.setattr(semantic, "_failed", False)
    monkeypatch.setattr(semantic, "_model", FakeModel())
    return s


TASK = "am I free on thursday afternoon"


def ids(r):
    return [x["id"] for x in r["selected"]]


def test_off_without_the_model_files(sem, env):
    assert not semantic.enabled(env["cfg"])
    r = router.route(sem, env["cfg"], TASK, log=False)
    assert "skill:user:gcal" not in ids(r) and all("meaning" not in x["why"] for x in r["selected"])


def test_meaning_finds_a_tool_with_no_word_in_common_but_never_pulls_in_memory(sem, env):
    semantic.model_dir(env["cfg"]).mkdir(parents=True)
    r = router.route(sem, env["cfg"], TASK, log=False)
    assert ids(r)[:1] == ["skill:user:gcal"] and r["selected"][0]["why"]["meaning"] > 0.5
    assert not any(i.startswith("experience:") for i in ids(r))  # memory still needs a shared word


def test_french_words_are_replaced_by_their_english_gloss():
    assert semantic.query_text("trouver où est définie une fonction") == "find defined function"


def test_a_broken_model_falls_back_to_keywords(sem, env, monkeypatch):
    semantic.model_dir(env["cfg"]).mkdir(parents=True)

    class Broken:
        def encode(self, texts):
            raise RuntimeError("corrupted model")

    monkeypatch.setattr(semantic, "_model", Broken())
    r = router.route(sem, env["cfg"], "merge pdf document", log=False)
    assert ids(r)[:1] == ["skill:user:pdf"] and all("meaning" not in x["why"] for x in r["selected"])
