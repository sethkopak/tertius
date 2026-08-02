"""State tracking: the thing resume correctness depends on."""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tertius.config import STATE_FILENAME
from tertius.state import (
    DONE,
    FAILED,
    IN_PROGRESS,
    PENDING,
    SKIPPED,
    StateStore,
)

from .fakes import make_audio


def names(paths) -> list[str]:
    return sorted(Path(p).name for p in paths)


@pytest.fixture()
def store(tmp_path):
    return StateStore.for_output_dir(tmp_path / "out")


def test_state_file_lands_in_output_dir(tmp_path):
    out = tmp_path / "out"
    store = StateStore.for_output_dir(out)
    store.add_files([str(tmp_path / "a.mp3")])
    assert (out / STATE_FILENAME).is_file()
    assert store.path == out / STATE_FILENAME


def test_add_files_registers_as_pending(store, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.wav")
    added = store.add_files(files)
    assert len(added) == 2
    assert store.summary()["pending"] == 2
    assert store.status_of(files[0]) == PENDING


def test_add_files_is_idempotent_and_preserves_status(store, tmp_path):
    (a,) = make_audio(tmp_path / "audio", "a.mp3")
    store.add_files([a])
    store.mark_done(a, outputs=["a.txt"])

    assert store.add_files([a]) == []  # nothing new
    assert store.status_of(a) == DONE  # and not reset to pending
    assert store.summary()["total"] == 1


def test_paths_normalise_to_one_entry(store, tmp_path):
    (a,) = make_audio(tmp_path / "audio", "a.mp3")
    store.add_files([str(a)])
    store.add_files([str(tmp_path / "audio" / "." / "a.mp3")])
    assert store.summary()["total"] == 1


def test_mark_transitions(store, tmp_path):
    (a,) = make_audio(tmp_path / "audio", "a.mp3")
    store.add_files([a])

    store.mark_in_progress(a)
    entry = store.get(a)
    assert entry["status"] == IN_PROGRESS and entry["started_at"]

    store.mark_done(a, outputs=["/out/a.txt"], language="en", duration=12.5)
    entry = store.get(a)
    assert entry["status"] == DONE
    assert entry["outputs"] == ["/out/a.txt"]
    assert entry["language"] == "en" and entry["duration"] == 12.5
    assert entry["finished_at"] >= entry["started_at"]

    store.mark_failed(a, "boom")
    entry = store.get(a)
    assert entry["status"] == FAILED and entry["error"] == "boom"

    store.mark_skipped(a)
    assert store.status_of(a) == SKIPPED


def test_mark_unknown_file_raises(store):
    with pytest.raises(KeyError):
        store.mark_done("/nope/missing.mp3")


def test_state_survives_reload(tmp_path):
    out = tmp_path / "out"
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    store = StateStore.for_output_dir(out)
    store.add_files(files)
    store.mark_done(files[0], outputs=["a.txt"])

    reloaded = StateStore.for_output_dir(out)
    assert reloaded.status_of(files[0]) == DONE
    assert reloaded.status_of(files[1]) == PENDING


def test_interrupted_in_progress_is_retranscribed_on_resume(tmp_path):
    """A file killed mid-transcription must not count as finished."""
    out = tmp_path / "out"
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")
    store = StateStore.for_output_dir(out)
    store.add_files(files)
    store.mark_done(files[0], outputs=["a.txt"])
    store.mark_in_progress(files[1])  # ...and then the process dies

    resumed = StateStore.for_output_dir(out)
    reset = resumed.reset_in_progress()

    assert names(reset) == ["b.mp3"]
    assert resumed.status_of(files[1]) == PENDING
    assert resumed.get(files[1])["started_at"] is None
    # Completed work is not redone; the interrupted file is.
    assert names(resumed.pending_files()) == ["b.mp3", "c.mp3"]
    assert resumed.status_of(files[0]) == DONE


def test_resume_skips_completed_and_keeps_failures(tmp_path):
    out = tmp_path / "out"
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")
    store = StateStore.for_output_dir(out)
    store.add_files(files)
    store.mark_done(files[0], outputs=["a.txt"])
    store.mark_failed(files[1], "corrupt")

    resumed = StateStore.for_output_dir(out)
    assert names(resumed.pending_files()) == ["c.mp3"]
    assert resumed.is_done(files[0]) is True
    assert resumed.is_done(files[1]) is False
    assert resumed.has_unfinished_work() is True

    resumed.mark_done(files[2], outputs=["c.txt"])
    assert resumed.has_unfinished_work() is False  # failures are not "unfinished"


def test_retry_failed_requeues_only_failures(store, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    store.add_files(files)
    store.mark_done(files[0], outputs=["a.txt"])
    store.mark_failed(files[1], "boom")

    retried = store.retry_failed()
    assert names(retried) == ["b.mp3"]
    assert store.status_of(files[1]) == PENDING
    assert store.get(files[1])["error"] is None
    assert store.status_of(files[0]) == DONE


def test_summary_counts_every_status(store, tmp_path):
    files = make_audio(tmp_path / "a", "a.mp3", "b.mp3", "c.mp3", "d.mp3")
    store.add_files(files)
    store.mark_done(files[0], outputs=[])
    store.mark_failed(files[1], "x")
    store.mark_in_progress(files[2])
    assert store.summary() == {
        "total": 4,
        "pending": 1,
        "in_progress": 1,
        "done": 1,
        "failed": 1,
        "skipped": 0,
    }


def test_remove_file(store, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    store.add_files(files)
    assert store.remove_file(files[0]) is True
    assert store.remove_file(files[0]) is False
    assert names(store.pending_files()) == ["b.mp3"]


def test_snapshot_is_a_copy(store, tmp_path):
    (a,) = make_audio(tmp_path / "audio", "a.mp3")
    store.add_files([a])
    snap = store.snapshot()
    snap["files"][0]["status"] = "tampered"
    assert store.status_of(a) == PENDING


def test_corrupt_state_file_is_quarantined_not_fatal(tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    (out / STATE_FILENAME).write_text("{not json", encoding="utf-8")

    store = StateStore.for_output_dir(out)

    assert store.summary()["total"] == 0
    assert (out / (STATE_FILENAME + ".corrupt")).is_file()


def test_writes_leave_valid_json_and_no_temp_files(tmp_path):
    out = tmp_path / "out"
    store = StateStore.for_output_dir(out)
    (a,) = make_audio(tmp_path / "audio", "a.mp3")
    store.add_files([a])
    store.mark_done(a, outputs=["a.txt"])

    data = json.loads((out / STATE_FILENAME).read_text(encoding="utf-8"))
    assert data["version"] == 1
    assert list(data["files"].values())[0]["status"] == DONE
    assert [p.name for p in out.iterdir() if p.suffix == ".tmp"] == []
