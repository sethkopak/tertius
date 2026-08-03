"""Changing the output directory must never lose the queue.

Reported 2026-08-03: add a file, press Begin, and the file vanishes from the
queue, the queue reads empty, and Begin greys out. Adding the file again works.

Cause: `start()` attached to the requested output directory whenever it differed
from the attached one, and each directory has its own state file — so it landed
on that folder's own, empty queue, found nothing pending, and errored, with the
files gone from the screen.
"""

from __future__ import annotations

import pytest
from tertius.jobs import JobError, JobManager
from tertius.state import MODE_ALIGN, StateStore

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio


def manager_with_fake_whisper() -> JobManager:
    """A manager that never touches the real model.

    Without this these tests would download large-v3-turbo on a CI runner - the
    suite's whole premise is that it decodes no audio and fetches nothing.
    """
    return JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=fake_transcribe_file,
    )


def test_pressing_begin_with_a_different_output_dir_keeps_the_queue(tmp_path):
    manager = manager_with_fake_whisper()
    first = tmp_path / "out-a"
    manager.attach(first)
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    manager.store.add_files(files)
    assert manager.status()["summary"]["pending"] == 2

    second = tmp_path / "out-b"
    manager.start(output_dir=second)
    manager.join(10)

    status = manager.status()
    assert status["output_dir"] == str(second.resolve())
    assert status["summary"]["total"] == 2, "the queued files should have followed"


def test_the_files_carried_over_keep_their_mode_and_matched_text(tmp_path):
    """Re-adding the paths from scratch would lose both."""
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "talk.mp3")
    (audio_dir / "talk.txt").write_text("the words", encoding="utf-8")

    manager = manager_with_fake_whisper()
    manager.attach(tmp_path / "out-a")
    manager.store.add_files([audio], match_reference_text=True)
    assert manager.store.get(audio)["mode"] == MODE_ALIGN

    manager.start(output_dir=tmp_path / "out-b")
    manager.join(10)

    carried = manager.store.get(audio)
    assert carried["mode"] == MODE_ALIGN
    assert carried["reference_text"] is not None


def test_a_file_already_finished_in_the_new_folder_is_not_reopened(tmp_path):
    """Carrying work over must not undo work the target folder already did."""
    files = make_audio(tmp_path / "audio", "a.mp3")
    second = tmp_path / "out-b"
    prior = StateStore.for_output_dir(second)
    prior.add_files(files)
    prior.mark_done(files[0], outputs=[str(second / "a.txt")])

    manager = manager_with_fake_whisper()
    manager.attach(tmp_path / "out-a")
    manager.store.add_files(files)

    with pytest.raises(JobError):  # nothing pending: it is already done there
        manager.start(output_dir=second)

    assert manager.store.get(files[0])["status"] == "done"


def test_switching_with_an_empty_queue_still_just_switches(tmp_path):
    manager = manager_with_fake_whisper()
    manager.attach(tmp_path / "out-a")
    second = tmp_path / "out-b"
    files = make_audio(tmp_path / "audio", "a.mp3")

    manager.start(files=files, output_dir=second)
    manager.join(10)

    assert manager.status()["output_dir"] == str(second.resolve())
    assert manager.status()["summary"]["total"] == 1


def test_adopt_leaves_entries_the_target_already_knows(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")
    files = make_audio(tmp_path / "audio", "a.mp3")
    store.add_files(files)
    store.mark_done(files[0], outputs=["a.txt"])

    taken = store.adopt([{"path": str(files[0].resolve()), "status": "pending"}])

    assert taken == 0
    assert store.get(files[0])["status"] == "done"


def test_adopted_entries_come_in_as_pending(tmp_path):
    """An entry mid-flight elsewhere is not trustworthy as in-progress here."""
    store = StateStore.for_output_dir(tmp_path / "out")

    taken = store.adopt([
        {"path": r"C:\somewhere\a.mp3", "name": "a.mp3", "status": "in_progress"},
    ])

    assert taken == 1
    assert store.snapshot()["files"][0]["status"] == "pending"


def test_unfinished_entries_reports_only_outstanding_work(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")
    store.add_files(files)
    store.mark_done(files[0], outputs=["a.txt"])
    store.mark_failed(files[1], "broke")

    assert [e["name"] for e in store.unfinished_entries()] == ["c.mp3"]
