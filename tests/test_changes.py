"""What changed in a stale entry's files, from git."""
import subprocess

from astroglia import experiences

from conftest import write


def git(cwd, *args):
    subprocess.run(["git", "-C", str(cwd), *args], check=True, capture_output=True)


def test_changes_since_shows_commits_and_diff(env):
    repo = env["tmp"] / "repo"
    f = write(repo / "cache.py", "TTL = 600\n")
    git(repo, "init", "-q"); git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "add", ".")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qm", "first")
    e = experiences.remember(env["store"], "TTL is 10 minutes", "Rate limit 60/h", kind="decision", files=[str(f)])
    env["store"].db.execute("UPDATE nodes SET verified='2000-01-01T00:00:00+00:00' WHERE id=?", (e["id"],)); env["store"].db.commit()
    f.write_text("TTL = 300\n", encoding="utf-8")
    git(repo, "-c", "user.email=a@b", "-c", "user.name=t", "commit", "-qam", "shorter cache TTL")
    ch = experiences.changes_since(env["store"], e["id"])
    assert len(ch) == 1 and ch[0]["state"] == "changed"
    assert any("shorter cache TTL" in c for c in ch[0]["commits"])
    assert "-TTL = 600" in ch[0]["diff"] and "+TTL = 300" in ch[0]["diff"]


def test_unchanged_and_non_git_files(env):
    f = write(env["tmp"] / "plain.txt", "a\n")
    e = experiences.remember(env["store"], "Plain", "about plain.txt", files=[str(f)])
    assert experiences.changes_since(env["store"], e["id"]) == []
    f.write_text("b\n", encoding="utf-8")
    ch = experiences.changes_since(env["store"], e["id"])
    assert ch[0]["state"] == "changed" and ch[0]["commits"] == []
