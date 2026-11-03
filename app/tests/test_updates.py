"""Check for updates, and install one: never touching what is not in a release."""

from __future__ import annotations

import os
import subprocess
import sys
import zipfile
from pathlib import Path

import pytest
from tertius import __version__, launcher, updates

from .fakes import wait_until


def release(tag, body="notes", draft=False, prerelease=False):
    return {
        "tag_name": tag,
        "name": f"Tertius {tag}",
        "body": body,
        "draft": draft,
        "prerelease": prerelease,
        "published_at": "2026-11-01T12:00:00Z",
        "html_url": f"https://github.com/{updates.REPO}/releases/tag/{tag}",
    }


def write_zip(path: Path, files: dict[str, str], top="sethkopak-tertius-abc1234"):
    with zipfile.ZipFile(path, "w") as bundle:
        bundle.writestr(f"{top}/", "")
        for name, text in files.items():
            bundle.writestr(f"{top}/{name}" if top else name, text)


def tertius_files(version="0.2.0", **extra):
    files = {
        "app/src/tertius/__init__.py": f'"""Tertius."""\n\n__version__ = "{version}"\n',
        "app/src/tertius/launcher.py": "# new launcher\n",
        "app/requirements.txt": "flask>=3.0\n",
        "README.md": "new readme\n",
    }
    files.update(extra)
    return files


@pytest.fixture()
def install(tmp_path):
    """A zip-downloaded copy of Tertius, with the user's things beside it."""
    root = tmp_path / "Tertius"
    (root / "app" / "src" / "tertius").mkdir(parents=True)
    (root / "app" / "src" / "tertius" / "__init__.py").write_text('__version__ = "0.1.0"\n')
    (root / "app" / "src" / "tertius" / "launcher.py").write_text("# old launcher\n")
    # Bytes, not text: text mode writes CRLF on Windows, and the zip has LF.
    (root / "app" / "requirements.txt").write_bytes(b"flask>=3.0\n")
    (root / "README.md").write_text("old readme\n")
    (root / "app" / ".venv").mkdir()
    (root / "app" / ".venv" / "marker").write_text("venv")
    (root / "transcripts").mkdir()
    (root / "transcripts" / "talk.txt").write_text("my transcript")
    return root


def fetcher(files, **kwargs):
    seen = []

    def fetch(url, target):
        seen.append(url)
        write_zip(target, files, **kwargs)

    fetch.seen = seen
    return fetch


# ------------------------------------------------------------------ versions

@pytest.mark.parametrize(
    "text, expected",
    [("v1.2.3", (1, 2, 3)), ("1.2", (1, 2, 0)), ("v2", (2, 0, 0)), ("0.1.0", (0, 1, 0)),
     ("latest", None), ("v1.2.3-beta", None), ("", None), (None, None)],
)
def test_versions_parse_strictly(text, expected):
    assert updates.parse_version(text) == expected


def test_the_package_and_pyproject_agree_on_the_version():
    """A release is compared against `__version__`; pip reads pyproject."""
    pyproject = (Path(updates.__file__).parents[2] / "pyproject.toml").read_text(encoding="utf-8")
    assert f'version = "{__version__}"' in pyproject


# ------------------------------------------------------------------ checking

def test_only_newer_published_releases_count():
    result = updates.check(
        "0.2.0",
        releases=[
            release("v0.3.0"),
            release("v0.4.0", draft=True),
            release("v0.5.0", prerelease=True),
            release("nightly"),
            release("v0.2.0"),
            release("v0.1.9"),
            release("v0.2.1"),
        ],
    )
    assert result["update_available"] is True
    assert result["latest"] == "v0.3.0"
    assert [r["tag"] for r in result["releases"]] == ["v0.3.0", "v0.2.1"]
    assert result["releases"][0]["notes"] == "notes"


def test_up_to_date_is_not_an_update():
    result = updates.check("0.3.0", releases=[release("v0.3.0"), release("v0.2.0")])
    assert result["update_available"] is False
    assert result["latest"] is None
    assert result["any_published"] is True


def test_no_releases_at_all_is_said_as_such():
    result = updates.check("0.1.0", releases=[release("v9.0.0", draft=True)])
    assert result["update_available"] is False
    assert result["any_published"] is False


def test_long_notes_and_long_histories_are_cut_short():
    many = [release(f"v1.{n}.0", body="x" * (updates.MAX_NOTES_CHARS + 50)) for n in range(15)]
    result = updates.check("0.1.0", releases=many)
    assert len(result["releases"]) == updates.MAX_RELEASES_SHOWN
    assert result["more_releases"] == 15 - updates.MAX_RELEASES_SHOWN
    assert result["releases"][0]["truncated"] is True
    assert len(result["releases"][0]["notes"]) < updates.MAX_NOTES_CHARS + 10


def test_a_network_failure_becomes_a_sentence(monkeypatch):
    import urllib.error

    def refuse(*args, **kwargs):
        raise urllib.error.URLError("no route to host")

    monkeypatch.setattr(updates.urllib.request, "urlopen", refuse)
    with pytest.raises(updates.UpdateError, match="Could not reach GitHub"):
        updates.fetch_releases()


# ---------------------------------------------------------------- installing

def test_an_update_replaces_the_code_and_nothing_else(install):
    fetch = fetcher(tertius_files(**{"app/src/tertius/updates.py": "# brand new\n"}))
    result = updates.apply("v0.2.0", root=install, current="0.1.0",
                           releases=[release("v0.2.0")], fetch=fetch)

    assert fetch.seen == [f"https://api.github.com/repos/{updates.REPO}/zipball/v0.2.0"]
    assert '"0.2.0"' in (install / "app" / "src" / "tertius" / "__init__.py").read_text()
    assert (install / "app" / "src" / "tertius" / "launcher.py").read_text() == "# new launcher\n"
    assert (install / "app" / "src" / "tertius" / "updates.py").read_text() == "# brand new\n"
    assert (install / "README.md").read_text() == "new readme\n"
    # requirements.txt is byte-identical, so it is left alone
    assert result["changed"] == 4
    assert (install / "app" / ".venv" / "marker").read_text() == "venv"
    assert (install / "transcripts" / "talk.txt").read_text() == "my transcript"
    assert not (install / "app" / updates.STAGING_DIRNAME).exists()


def test_a_release_cannot_write_into_the_environment_or_git(install):
    files = tertius_files(**{"app/.venv/marker": "replaced", ".git/config": "evil"})
    updates.apply("v0.2.0", root=install, current="0.1.0",
                  releases=[release("v0.2.0")], fetch=fetcher(files))
    assert (install / "app" / ".venv" / "marker").read_text() == "venv"
    assert not (install / ".git").exists()


@pytest.mark.parametrize("bad", ["../escape.txt", "app/../../escape.txt", "C:/escape.txt"])
def test_a_path_outside_the_install_refuses_the_whole_release(install, bad):
    files = tertius_files(**{bad: "x"})
    with pytest.raises(updates.UpdateError, match="unsafe path"):
        updates.apply("v0.2.0", root=install, current="0.1.0",
                      releases=[release("v0.2.0")], fetch=fetcher(files))
    assert (install / "README.md").read_text() == "old readme\n"
    assert not (install.parent / "escape.txt").exists()


def test_a_tag_that_disagrees_with_its_code_is_not_installed(install):
    """Otherwise it installs, reports the old number, and offers itself forever."""
    with pytest.raises(updates.UpdateError, match="contains version 0.1.0"):
        updates.apply("v0.2.0", root=install, current="0.1.0",
                      releases=[release("v0.2.0")], fetch=fetcher(tertius_files("0.1.0")))
    assert (install / "README.md").read_text() == "old readme\n"


def test_something_that_is_not_tertius_is_not_installed(install):
    files = {"app/src/tertius/__init__.py": '__version__ = "0.2.0"\n', "README.md": "?"}
    with pytest.raises(updates.UpdateError, match="not a Tertius"):
        updates.apply("v0.2.0", root=install, current="0.1.0",
                      releases=[release("v0.2.0")], fetch=fetcher(files))
    assert (install / "README.md").read_text() == "old readme\n"


def test_only_a_published_newer_tag_is_installed(install):
    for tag, releases in [
        ("v0.2.0", [release("v0.2.0", draft=True)]),
        ("v0.1.0", [release("v0.1.0")]),
        ("v9.9.9", [release("v0.2.0")]),
    ]:
        with pytest.raises(updates.UpdateError, match="not a published release"):
            updates.apply(tag, root=install, current="0.1.0", releases=releases,
                          fetch=fetcher(tertius_files()))


def test_a_git_checkout_is_updated_with_git_not_the_zip(install, monkeypatch):
    (install / ".git").mkdir()
    calls = []
    monkeypatch.setattr(updates, "apply_git", lambda tag, root, current: calls.append(tag) or {})
    zip_fetch = fetcher(tertius_files())
    updates.apply("v0.2.0", root=install, current="0.1.0",
                  releases=[release("v0.2.0")], fetch=zip_fetch)
    assert calls == ["v0.2.0"]
    assert zip_fetch.seen == []
    assert (install / "README.md").read_text() == "old readme\n"


# ------------------------------------------------------------ git checkouts

def git(root, *args):
    done = subprocess.run(["git", "-C", str(root), *args], capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    return done.stdout.strip()


def commit_version(repo, version, tag=None):
    init = repo / "app" / "src" / "tertius" / "__init__.py"
    init.parent.mkdir(parents=True, exist_ok=True)
    init.write_text(f'__version__ = "{version}"\n')
    (repo / "README.md").write_text(f"readme {version}\n")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", version)
    if tag:
        git(repo, "tag", tag)


@pytest.fixture()
def checkout(tmp_path, monkeypatch):
    """An upstream at 0.1.0 with v0.2.0 tagged after it, and a clone at 0.1.0."""
    for key in ("AUTHOR", "COMMITTER"):
        monkeypatch.setenv(f"GIT_{key}_NAME", "Test")
        monkeypatch.setenv(f"GIT_{key}_EMAIL", "test@example.invalid")
    upstream = tmp_path / "upstream"
    upstream.mkdir()
    git(upstream, "init", "-q")
    commit_version(upstream, "0.1.0")
    clone = tmp_path / "clone"
    subprocess.run(["git", "clone", "-q", str(upstream), str(clone)], check=True)
    commit_version(upstream, "0.2.0", tag="v0.2.0")
    return upstream, clone


def version_in(clone):
    return (clone / "app" / "src" / "tertius" / "__init__.py").read_text()


def test_a_clean_checkout_moves_forward_to_the_release(checkout):
    upstream, clone = checkout
    result = updates.apply_git("v0.2.0", clone, current="0.1.0", source=str(upstream))
    assert '"0.2.0"' in version_in(clone)
    assert git(clone, "rev-parse", "HEAD") == git(upstream, "rev-parse", "v0.2.0")
    assert result["changed"] == 2


def test_untracked_files_do_not_stop_it(checkout):
    upstream, clone = checkout
    (clone / "transcripts").mkdir()
    (clone / "transcripts" / "talk.srt").write_text("mine")
    updates.apply_git("v0.2.0", clone, current="0.1.0", source=str(upstream))
    assert (clone / "transcripts" / "talk.srt").read_text() == "mine"


def test_uncommitted_changes_are_never_overwritten(checkout):
    upstream, clone = checkout
    (clone / "README.md").write_text("work in progress\n")
    assert "README.md" in updates.git_blocker(clone)
    with pytest.raises(updates.UpdateError, match="uncommitted changes"):
        updates.apply_git("v0.2.0", clone, current="0.1.0", source=str(upstream))
    assert (clone / "README.md").read_text() == "work in progress\n"
    assert '"0.1.0"' in version_in(clone)


def test_local_commits_stop_it_rather_than_merge(checkout):
    upstream, clone = checkout
    (clone / "notes.md").write_text("local\n")
    git(clone, "add", "notes.md")
    git(clone, "commit", "-q", "-m", "local work")
    before = git(clone, "rev-parse", "HEAD")
    with pytest.raises(updates.UpdateError, match="commits that v0.2.0 does not"):
        updates.apply_git("v0.2.0", clone, current="0.1.0", source=str(upstream))
    assert git(clone, "rev-parse", "HEAD") == before


def test_a_detached_head_is_not_moved(checkout):
    upstream, clone = checkout
    git(clone, "checkout", "-q", "--detach")
    assert "detached" in updates.git_blocker(clone)


def test_a_git_tag_that_disagrees_with_its_code_is_not_installed(checkout):
    upstream, clone = checkout
    commit_version(upstream, "0.2.5", tag="v0.3.0")
    with pytest.raises(updates.UpdateError, match="contains version 0.2.5"):
        updates.apply_git("v0.3.0", clone, current="0.1.0", source=str(upstream))
    assert '"0.1.0"' in version_in(clone)


def test_the_dialog_is_told_why_before_the_click(checkout, monkeypatch):
    upstream, clone = checkout
    (clone / "README.md").write_text("work in progress\n")
    monkeypatch.setattr(updates, "install_dir", lambda: clone)
    result = updates.check("0.1.0", releases=[release("v0.2.0")])
    assert result["git_checkout"] is True
    assert "uncommitted changes" in result["blocked"]


def test_a_failure_part_way_puts_every_file_back(install, monkeypatch):
    files = tertius_files(**{"app/src/tertius/zzz_new.py": "# new\n"})
    real_replace = os.replace
    calls = []

    def flaky(src, dst):
        calls.append(dst)
        if Path(dst).name == "zzz_new.py":
            raise PermissionError("in use")
        return real_replace(src, dst)

    monkeypatch.setattr(updates.os, "replace", flaky)
    with pytest.raises(updates.UpdateError, match="Nothing was changed"):
        updates.apply("v0.2.0", root=install, current="0.1.0",
                      releases=[release("v0.2.0")], fetch=fetcher(files))
    assert len(calls) > 1  # some files really had been replaced first
    assert (install / "README.md").read_text() == "old readme\n"
    assert (install / "app" / "src" / "tertius" / "launcher.py").read_text() == "# old launcher\n"
    assert '"0.1.0"' in (install / "app" / "src" / "tertius" / "__init__.py").read_text()
    assert not (install / "app" / "src" / "tertius" / "zzz_new.py").exists()
    assert not (install / "app" / updates.STAGING_DIRNAME).exists()


@pytest.mark.skipif(sys.platform == "win32", reason="Windows has no executable bit")
def test_the_shell_launcher_stays_executable(install):
    fetch_files = tertius_files()

    def fetch(url, target):
        write_zip(target, fetch_files)
        with zipfile.ZipFile(target, "a") as bundle:
            info = zipfile.ZipInfo("sethkopak-tertius-abc1234/start-tertius.sh")
            info.external_attr = 0o100755 << 16
            bundle.writestr(info, "#!/bin/sh\n")

    updates.apply("v0.2.0", root=install, current="0.1.0",
                  releases=[release("v0.2.0")], fetch=fetch)
    assert os.access(install / "start-tertius.sh", os.X_OK)


# ---------------------------------------------------------------------- HTTP

def test_the_check_route_says_whether_a_job_is_running(api, monkeypatch):
    monkeypatch.setattr(updates, "fetch_releases", lambda: [release("v99.0.0")])
    body = api.client.get("/api/update/check").get_json()
    assert body["update_available"] is True
    assert body["latest"] == "v99.0.0"
    assert body["job_running"] is False


def test_the_check_route_passes_on_a_github_failure(api, monkeypatch):
    def fail():
        raise updates.UpdateError("Could not reach GitHub (offline).")

    monkeypatch.setattr(updates, "fetch_releases", fail)
    res = api.client.get("/api/update/check")
    assert res.status_code == 502
    assert "Could not reach GitHub" in res.get_json()["error"]


def test_the_version_route(api):
    assert api.client.get("/api/version").get_json() == {"version": __version__}


def test_install_refuses_another_origin(api, monkeypatch):
    called = []
    monkeypatch.setattr(updates, "apply", lambda tag: called.append(tag))
    res = api.client.post("/api/update/apply", json={"tag": "v9.0.0"},
                          headers={"Origin": "https://evil.example"})
    assert res.status_code == 403
    assert called == []


def test_install_needs_a_json_tag(api, monkeypatch):
    """A cross-site form post cannot send JSON, so it cannot get this far."""
    called = []
    monkeypatch.setattr(updates, "apply", lambda tag: called.append(tag))
    res = api.client.post("/api/update/apply", data="tag=v9.0.0",
                          content_type="application/x-www-form-urlencoded")
    assert res.status_code == 400
    assert called == []


def test_install_without_a_launcher_says_to_restart_by_hand(api, monkeypatch):
    monkeypatch.delenv(updates.LAUNCHER_ENV, raising=False)
    monkeypatch.setattr(updates, "apply", lambda tag: {"installed": tag, "previous": "0.1.0",
                                                      "changed": 3})
    exits = []
    monkeypatch.setattr(os, "_exit", exits.append)
    res = api.client.post("/api/update/apply", json={"tag": "v9.0.0"},
                          headers={"Origin": "http://localhost"})
    assert res.status_code == 200
    assert res.get_json()["restarting"] is False
    assert exits == []


def test_install_under_the_launcher_exits_to_be_restarted(api, monkeypatch):
    monkeypatch.setenv(updates.LAUNCHER_ENV, "1")
    monkeypatch.setattr(updates, "apply", lambda tag: {"installed": tag, "previous": "0.1.0",
                                                      "changed": 3})
    exits = []
    monkeypatch.setattr(os, "_exit", exits.append)
    res = api.client.post("/api/update/apply", json={"tag": "v9.0.0"})
    assert res.get_json()["restarting"] is True
    wait_until(lambda: exits, timeout=5, description="restart exit")
    assert exits == [updates.RESTART_EXIT_CODE]


def test_install_is_refused_while_a_job_runs(api, monkeypatch):
    monkeypatch.setattr(api.manager, "is_running", lambda: True)
    called = []
    monkeypatch.setattr(updates, "apply", lambda tag: called.append(tag))
    res = api.client.post("/api/update/apply", json={"tag": "v9.0.0"})
    assert res.status_code == 409
    assert called == []


def test_the_page_offers_the_button(api):
    page = api.client.get("/").data
    assert b'id="btn-check-updates"' in page
    assert b'id="update-dialog"' in page


# ------------------------------------------------------------------ launcher

def test_the_launcher_and_the_server_agree_on_the_restart_contract():
    assert launcher.RESTART_EXIT_CODE == updates.RESTART_EXIT_CODE
    assert launcher.LAUNCHER_ENV == updates.LAUNCHER_ENV


def test_changed_requirements_are_noticed(tmp_path, monkeypatch):
    app = tmp_path / "app"
    venv = app / ".venv"
    venv.mkdir(parents=True)
    requirements = app / "requirements.txt"
    requirements.write_bytes(b"flask>=3.0\r\n")
    monkeypatch.setattr(launcher, "app_dir", lambda: app)

    # An environment from before the stamp existed is taken as matching.
    assert launcher.requirements_changed(venv) is False
    assert launcher.requirements_stamp(venv).is_file()
    # The same file with other line endings is the same requirements.
    requirements.write_bytes(b"flask>=3.0\n")
    assert launcher.requirements_changed(venv) is False
    requirements.write_bytes(b"flask>=3.0\nnew-dependency\n")
    assert launcher.requirements_changed(venv) is True
    launcher.stamp_requirements(venv)
    assert launcher.requirements_changed(venv) is False


def test_an_update_exit_starts_the_new_launcher(monkeypatch):
    runs = []

    class Done:
        def __init__(self, code):
            self.returncode = code

    def fake_run(command, env=None, **kwargs):
        runs.append((command, env))
        return Done(launcher.RESTART_EXIT_CODE if len(runs) == 1 else 0)

    monkeypatch.setattr(launcher, "handle_existing", lambda url, say: "launch")
    monkeypatch.setattr(launcher, "ensure_environment", lambda say: Path(sys.executable))
    monkeypatch.setattr(launcher, "refresh_windows_shortcut", lambda say: None)
    monkeypatch.setattr(launcher, "apply_windows_folder_icon", lambda say: None)
    monkeypatch.setattr(launcher, "refresh_linux_desktop_entry", lambda say: None)
    monkeypatch.setattr(subprocess, "run", fake_run)

    assert launcher.main(["--port", "5099"], say=lambda *a: None) == 0
    server, relaunch = runs
    assert server[1][launcher.LAUNCHER_ENV] == "1"
    assert relaunch[0][1] == str(Path(launcher.__file__).resolve())
    assert relaunch[0][2:] == ["--port", "5099", "--no-browser"]
