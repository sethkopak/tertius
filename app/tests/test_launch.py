"""CLI entry point: argument handling and the browser opener.

The opener had a silent-failure bug once (a broken shell-quoted helper that
polled forever and never opened anything), hence the coverage.
"""

from __future__ import annotations

import sys
import threading

import pytest
from tertius import __main__ as entry


def test_open_browser_is_opt_in():
    assert entry.build_parser().parse_args([]).open_browser is False
    assert entry.build_parser().parse_args(["--open-browser"]).open_browser is True


def test_defaults():
    args = entry.build_parser().parse_args([])
    assert (args.host, args.port, args.verbose) == ("127.0.0.1", 5005, False)


def test_opens_once_the_server_answers(monkeypatch):
    """It must wait for a real response, not just fire on a timer."""
    calls = {"probes": 0}
    opened = []

    class FakeResponse:
        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    def fake_urlopen(url, timeout=None):
        calls["probes"] += 1
        if calls["probes"] < 3:  # server still starting
            raise OSError("connection refused")
        assert url.endswith("/api/status")
        return FakeResponse()

    monkeypatch.setattr(entry.urllib.request, "urlopen", fake_urlopen)
    monkeypatch.setattr(entry.time, "sleep", lambda _s: None)
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: opened.append(url) or True)

    assert entry.open_browser_when_ready("http://127.0.0.1:5005/") is True
    assert opened == ["http://127.0.0.1:5005/"]
    assert calls["probes"] == 3


def test_gives_up_instead_of_polling_forever(monkeypatch):
    opened = []
    monkeypatch.setattr(
        entry.urllib.request,
        "urlopen",
        lambda url, timeout=None: (_ for _ in ()).throw(OSError("refused")),
    )
    monkeypatch.setattr(entry.time, "sleep", lambda _s: None)
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: opened.append(url))

    assert entry.open_browser_when_ready("http://127.0.0.1:5005/", timeout=0.2) is False
    assert opened == []  # never opened a tab for a server that never came up


def test_a_browser_that_refuses_to_open_is_not_fatal(monkeypatch):
    class FakeResponse:
        def read(self, _n=None):
            return b"{}"

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    monkeypatch.setattr(
        entry.urllib.request, "urlopen", lambda url, timeout=None: FakeResponse()
    )
    monkeypatch.setattr(
        entry.webbrowser,
        "open",
        lambda url: (_ for _ in ()).throw(RuntimeError("no browser")),
    )

    assert entry.open_browser_when_ready("http://127.0.0.1:5005/") is False


def test_opener_runs_off_the_main_thread(monkeypatch, tmp_path):
    """The server must not wait on the browser."""
    seen = {}
    monkeypatch.setattr(
        entry, "create_app", lambda output_dir: _StubApp(seen)
    )

    def fake_thread(target, args, name, daemon):
        seen["thread"] = (target, name, daemon)
        return _StubThread()

    monkeypatch.setattr(entry.threading, "Thread", fake_thread)
    entry.main(["--output-dir", str(tmp_path), "--open-browser", "--port", "5999"])

    target, name, daemon = seen["thread"]
    assert target is entry.open_browser_when_ready
    assert daemon is True and name == "browser-opener"
    assert seen["ran"] is True  # app.run() still happened


def test_reuse_existing_does_not_start_a_second_server(monkeypatch, tmp_path):
    """Windows lets a second process bind a port already in use, which would give
    two job managers one state file. The second launch must bow out."""
    opened = []
    monkeypatch.setattr(entry, "server_already_running", lambda url, **kw: True)
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: opened.append(url))
    monkeypatch.setattr(
        entry,
        "create_app",
        lambda output_dir: pytest.fail("must not build an app when reusing"),
    )

    code = entry.main(
        ["--output-dir", str(tmp_path), "--reuse-existing", "--open-browser"]
    )

    assert code == 0
    assert opened == ["http://127.0.0.1:5005/"]


def test_reuse_existing_does_not_touch_the_running_job_state(monkeypatch, tmp_path):
    """create_app attaches to the state file and resets in-progress entries, so
    the running check has to happen first."""
    from tertius.state import IN_PROGRESS, StateStore

    store = StateStore.for_output_dir(tmp_path)
    store.add_files([tmp_path / "busy.mp3"])
    store.mark_in_progress(tmp_path / "busy.mp3")

    monkeypatch.setattr(entry, "server_already_running", lambda url, **kw: True)
    monkeypatch.setattr(entry.webbrowser, "open", lambda url: True)
    entry.main(["--output-dir", str(tmp_path), "--reuse-existing", "--open-browser"])

    # The other process's in-flight file is untouched.
    assert StateStore.for_output_dir(tmp_path).status_of(tmp_path / "busy.mp3") == (
        IN_PROGRESS
    )


def test_without_reuse_flag_it_starts_normally(monkeypatch, tmp_path):
    seen = {}
    monkeypatch.setattr(entry, "server_already_running", lambda url, **kw: True)
    monkeypatch.setattr(entry, "create_app", lambda output_dir: _StubApp(seen))
    entry.main(["--output-dir", str(tmp_path)])
    assert seen["ran"] is True


def test_server_already_running_probes_the_status_endpoint(monkeypatch):
    class FakeResponse:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

    seen = {}

    def fake_urlopen(url, timeout=None):
        seen["url"] = url
        return FakeResponse()

    monkeypatch.setattr(entry.urllib.request, "urlopen", fake_urlopen)
    assert entry.server_already_running("http://127.0.0.1:5005/") is True
    assert seen["url"] == "http://127.0.0.1:5005/api/status"


def test_server_already_running_is_false_when_nothing_answers(monkeypatch):
    monkeypatch.setattr(
        entry.urllib.request,
        "urlopen",
        lambda url, timeout=None: (_ for _ in ()).throw(OSError("refused")),
    )
    assert entry.server_already_running("http://127.0.0.1:5005/") is False


class _StubThread:
    def start(self):
        pass


class _StubApp:
    def __init__(self, seen):
        self._seen = seen
        self.config = {"JOB_MANAGER": _StubManager()}

    def run(self, **kwargs):
        self._seen["ran"] = True


class _StubManager:
    def status(self, include_files=True):
        return {"can_resume": False, "summary": {}}


def test_thread_is_real_when_not_stubbed():
    """Sanity: the module actually uses threading.Thread, not a stub of our own."""
    assert entry.threading is threading


@pytest.mark.parametrize("flag", ["--host", "--port", "--output-dir"])
def test_parser_accepts_documented_flags(flag):
    assert flag in entry.build_parser().format_help()


# ------------------------------------------------------------- the folder icon


@pytest.mark.skipif(sys.platform != "win32", reason="desktop.ini is Windows-only")
def test_the_folder_icon_survives_its_own_attributes(tmp_path, monkeypatch):
    """The launcher set the flags that made its own next run fail.

    Explorer only honours a *hidden and system* `desktop.ini`, so the first run
    marks it as both - and Windows then refuses to open a file carrying either
    attribute for writing. Every launch after the first printed "could not set
    the folder icon: [Errno 13] Permission denied", which it did for seven
    weeks before anybody mentioned it.

    Harmless while the folder stays put. Not harmless once it moves, because
    `IconResource` is an absolute path: the rewrite that a moved folder needs
    is exactly the one that could not happen.
    """
    from tertius import launcher

    assets = tmp_path / "app" / "assets"
    assets.mkdir(parents=True)
    (assets / "tertius.ico").touch()
    monkeypatch.setattr(launcher, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher, "app_dir", lambda: tmp_path / "app")

    said: list[str] = []
    assert launcher.apply_windows_folder_icon(say=said.append) is True
    assert said == [], said
    ini = tmp_path / "desktop.ini"
    assert ini.is_file()

    # Second run: the file is hidden+system by now. This is the one that broke.
    said.clear()
    assert launcher.apply_windows_folder_icon(say=said.append) is True
    assert said == [], said

    # And a moved folder, where the content genuinely has to change.
    moved = tmp_path / "elsewhere" / "assets"
    moved.mkdir(parents=True)
    (moved / "tertius.ico").touch()
    monkeypatch.setattr(launcher, "app_dir", lambda: tmp_path / "elsewhere")

    said.clear()
    assert launcher.apply_windows_folder_icon(say=said.append) is True
    assert said == [], said
    assert "elsewhere" in ini.read_text(encoding="utf-8", newline="")


@pytest.mark.skipif(sys.platform != "win32", reason="desktop.ini is Windows-only")
def test_a_missing_icon_file_is_not_an_error(tmp_path, monkeypatch):
    """Cosmetic, and never the reason a launch fails."""
    from tertius import launcher

    (tmp_path / "app" / "assets").mkdir(parents=True)
    monkeypatch.setattr(launcher, "project_dir", lambda: tmp_path)
    monkeypatch.setattr(launcher, "app_dir", lambda: tmp_path / "app")

    said: list[str] = []
    assert launcher.apply_windows_folder_icon(say=said.append) is False
    assert not (tmp_path / "desktop.ini").exists()
