"""Tertius must come back up pointing where you left it.

From a real incident on 2026-08-03. A 99-file batch finished into a chosen
output folder; the server was restarted a few times; each restart reattached to
the *default* folder, which keeps its own separate queue and still held the same
99 files marked pending. The finished work looked unfinished, and starting the
queue began re-transcribing files that were already done.

Nothing was lost - the transcripts were in the other folder all along - but the
next batch would have burned hours redoing them.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from tertius import settings
from tertius.__main__ import resolve_output_dir
from tertius.jobs import JobManager


@pytest.fixture
def chosen(tmp_path):
    directory = tmp_path / "Bible Study App" / "Transcripts"
    directory.mkdir(parents=True)
    return directory


# ------------------------------------------------------------------ precedence

def test_an_explicit_directory_always_wins(chosen, tmp_path):
    settings.remember_output_dir(chosen)
    asked_for = tmp_path / "somewhere-else"

    resolved, why = resolve_output_dir(str(asked_for))

    assert resolved == asked_for.resolve()
    assert why == "asked for"


def test_the_last_directory_is_used_when_none_is_given(chosen):
    settings.remember_output_dir(chosen)

    resolved, why = resolve_output_dir(None)

    assert resolved == chosen.resolve()
    assert why == "remembered from last time"


def test_the_default_is_used_when_nothing_is_remembered():
    resolved, why = resolve_output_dir(None)

    assert why == "the default"
    assert resolved.name == "transcripts"


def test_a_remembered_directory_that_has_gone_falls_back(chosen):
    """A folder on an unplugged drive must not break the launch."""
    settings.remember_output_dir(chosen)
    chosen.rmdir()

    resolved, why = resolve_output_dir(None)

    assert why == "the default"
    assert resolved != chosen


# ------------------------------------------------------------------- recording

def test_attaching_records_the_directory(chosen):
    JobManager().attach(chosen)

    assert settings.remembered_output_dir() == chosen.resolve()


def test_switching_directories_records_the_new_one(chosen, tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    manager = JobManager()

    manager.attach(chosen)
    manager.attach(other)

    assert settings.remembered_output_dir() == other.resolve()


def test_the_whole_round_trip(chosen):
    """Choose a folder, restart, come back to the same folder."""
    JobManager().attach(chosen)

    resolved, why = resolve_output_dir(None)

    assert resolved == chosen.resolve()
    assert why == "remembered from last time"


# --------------------------------------------------------------- robustness

def test_an_unreadable_session_file_is_ignored(monkeypatch, tmp_path):
    broken = tmp_path / "broken.json"
    broken.write_text("{not json at all", encoding="utf-8")
    monkeypatch.setenv("TERTIUS_SESSION_FILE", str(broken))

    assert settings.remembered_output_dir() is None
    assert resolve_output_dir(None)[1] == "the default"


def test_a_session_file_that_cannot_be_written_is_not_fatal(monkeypatch, tmp_path):
    """Losing a preference is a nuisance; failing to start over one is a bug."""
    monkeypatch.setenv(
        "TERTIUS_SESSION_FILE", str(tmp_path / "no-such-dir" / "x" / "s.json")
    )

    def refuse(*args, **kwargs):
        raise OSError("read-only file system")

    monkeypatch.setattr(Path, "mkdir", refuse)

    assert settings.remember_output_dir(tmp_path) is False


def test_recording_the_same_directory_twice_does_not_rewrite_it(chosen, monkeypatch):
    settings.remember_output_dir(chosen)

    writes = []
    monkeypatch.setattr(settings, "_write", lambda data: writes.append(data) or True)
    settings.remember_output_dir(chosen)

    assert writes == []


# ------------------------------------------------------------- the default itself

def test_the_default_does_not_depend_on_the_working_directory(monkeypatch, tmp_path):
    """It used to be cwd/transcripts, which moved with the shell."""
    from tertius.config import default_output_dir

    monkeypatch.delenv("TERTIUS_OUTPUT_DIR", raising=False)
    before = default_output_dir()
    monkeypatch.chdir(tmp_path)

    assert default_output_dir() == before


def test_the_env_var_still_overrides_the_default(monkeypatch, tmp_path):
    from tertius.config import default_output_dir

    monkeypatch.setenv("TERTIUS_OUTPUT_DIR", str(tmp_path))

    assert default_output_dir() == tmp_path.resolve()
