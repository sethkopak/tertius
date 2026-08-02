"""Pairing audio with supplied text, and what happens when there is none."""

from __future__ import annotations

from pathlib import Path

import pytest
from tertius.config import TranscriptionOptions
from tertius.jobs import JobError, JobManager
from tertius.state import (
    MODE_ALIGN,
    MODE_SKIP,
    MODE_TRANSCRIBE,
    MODE_UNDECIDED,
    SKIPPED,
    StateStore,
)

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio


def write_text(directory: Path, name: str, body: str = "Some spoken words here.") -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_text_file_is_matched_by_name(tmp_path):
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "VolA01.mp3")
    write_text(audio_dir, "VolA01.txt")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)

    entry = store.get(audio)
    assert entry["mode"] == MODE_ALIGN
    assert Path(entry["reference_text"]).name == "VolA01.txt"


def test_matching_ignores_case(tmp_path):
    """Windows users should not have to think about this."""
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "VolA01.mp3")
    write_text(audio_dir, "vola01.TXT")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)

    assert store.get(audio)["mode"] == MODE_ALIGN


def test_a_near_miss_is_not_matched(tmp_path):
    """VolA01.mp3 must not grab VolA02.txt."""
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "VolA01.mp3")
    write_text(audio_dir, "VolA02.txt")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)

    entry = store.get(audio)
    assert entry["mode"] == MODE_UNDECIDED
    assert entry["reference_text"] is None


def test_without_the_feature_everything_just_transcribes(tmp_path):
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "VolA01.mp3")
    write_text(audio_dir, "VolA01.txt")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio])  # feature off

    assert store.get(audio)["mode"] == MODE_TRANSCRIBE


def test_files_without_text_are_flagged_for_a_decision(tmp_path):
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "a.mp3", "b.mp3")
    write_text(audio_dir, "a.txt")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(files, match_reference_text=True)

    undecided = store.files_needing_a_decision()
    assert [Path(p).name for p in undecided] == ["b.mp3"]


def test_rematch_picks_up_text_added_later(tmp_path):
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "a.mp3")
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)
    assert store.get(audio)["mode"] == MODE_UNDECIDED

    write_text(audio_dir, "a.txt")  # the user adds it
    assert store.rematch_reference_texts() == 1
    assert store.get(audio)["mode"] == MODE_ALIGN


def test_set_mode_requires_a_text_file_to_align(tmp_path):
    (audio,) = make_audio(tmp_path / "audio", "a.mp3")
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)

    with pytest.raises(ValueError, match="needs a text file"):
        store.set_mode(audio, MODE_ALIGN)

    manual = write_text(tmp_path / "elsewhere", "whatever.txt")
    entry = store.set_mode(audio, MODE_ALIGN, reference_text=str(manual))
    assert entry["reference_text"] == str(manual)


def test_a_job_will_not_start_while_files_are_undecided(tmp_path):
    """The point of asking is that we do not quietly pick for them."""
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "a.mp3", "b.mp3")
    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    manager.store.add_files(files, match_reference_text=True)

    with pytest.raises(JobError, match="no matching text file"):
        manager.start()

    assert manager.is_running() is False


def test_deciding_lets_the_job_run(tmp_path):
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "a.mp3", "b.mp3")
    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    manager.store.add_files(files, match_reference_text=True)
    manager.store.set_mode(files[0], MODE_TRANSCRIBE)
    manager.store.set_mode(files[1], MODE_SKIP)

    manager.start()
    manager.join(20)

    summary = manager.status()["summary"]
    assert summary["done"] == 1
    assert summary[SKIPPED] == 1
    assert (tmp_path / "out" / "a.txt").is_file()
    assert not (tmp_path / "out" / "b.txt").exists()  # skipped, never written


def test_skipped_files_are_not_transcribed(tmp_path):
    (audio,) = make_audio(tmp_path / "audio", "a.mp3")
    seen = []

    class Watcher(FakeTranscriber):
        def transcribe(self, path):
            seen.append(str(path))
            return super().transcribe(path)

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: Watcher(options),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    manager.store.add_files([audio])
    manager.store.set_mode(audio, MODE_SKIP)

    # Still pending, so the job starts - and the file is passed over untouched.
    manager.start()
    manager.join(20)

    assert seen == []  # the model never saw it
    assert manager.store.status_of(audio) == SKIPPED
    assert not (tmp_path / "out" / "a.txt").exists()


def test_alignment_granularity_is_validated():
    assert TranscriptionOptions(alignment_granularity="sentence")
    with pytest.raises(ValueError, match="granularity"):
        TranscriptionOptions(alignment_granularity="per-word")
