"""Progress *through* a file, which is what the UI's active row is built on.

The worker offers the transcriber a per-segment callback; a transcribe function
that does not want one must never be handed it, because the test doubles - and
any future stand-in - are free to keep the older signature.
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest
from tertius.jobs import JobManager
from tertius.transcribe import write_outputs

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio, wait_until


class WatchedTranscriber(FakeTranscriber):
    """Emits its segments through the callback, like the real one does."""

    def __init__(self, options):
        super().__init__(options)
        self.pause: threading.Event | None = None

    def transcribe(self, path, word_timestamps=False, on_segment=None):
        result = super().transcribe(path)
        if on_segment is not None:
            first, second = result.segments
            on_segment(first, result.duration)
            if self.pause is not None:
                self.pause.wait(timeout=10)  # hold the file open mid-way
            on_segment(second, result.duration)
        return result


def watched_transcribe_file(transcriber, source, output_dir, on_segment=None):
    result = transcriber.transcribe(source, on_segment=on_segment)
    outputs = write_outputs(
        Path(source), result, Path(output_dir), transcriber.options.formats
    )
    return outputs, result


def watching_factory(pause=None):
    def make(options):
        transcriber = WatchedTranscriber(options)
        transcriber.pause = pause
        return transcriber

    return make


def test_the_active_file_reports_progress_and_an_excerpt(tmp_path):
    pause = threading.Event()
    manager = JobManager(
        transcriber_factory=watching_factory(pause),
        transcribe_fn=watched_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    audio = make_audio(tmp_path / "audio", "talk.mp3")
    manager.store.add_files(audio)

    manager.start()
    try:
        active = wait_until(
            lambda: manager.status()["active"] if manager.status()["active"]["excerpt"] else None,
            description="the first segment to land",
        )
        # One segment of 1.5s into 3.0s of audio, and the words it carried.
        assert active["progress"] == pytest.approx(0.5)
        assert active["excerpt"] == "hello from talk"
        assert active["path"] == str(Path(audio[0]).resolve())
        assert active["audio_seconds"] == 3.0
    finally:
        pause.set()
    manager.join(10)


def test_the_live_fields_are_cleared_once_the_file_settles(tmp_path):
    manager = JobManager(
        transcriber_factory=watching_factory(), transcribe_fn=watched_transcribe_file
    )
    manager.attach(tmp_path / "out")
    manager.store.add_files(make_audio(tmp_path / "audio", "one.mp3", "two.mp3"))

    manager.start()
    manager.join(10)

    active = manager.status()["active"]
    assert active["path"] is None
    assert active["excerpt"] == ""
    assert active["progress"] is None


def test_a_transcribe_function_without_the_callback_is_left_alone(tmp_path):
    """The older three-argument signature keeps working, untouched."""
    manager = JobManager(
        transcriber_factory=FakeTranscriber, transcribe_fn=fake_transcribe_file
    )
    manager.attach(tmp_path / "out")
    manager.store.add_files(make_audio(tmp_path / "audio", "talk.mp3"))

    manager.start()
    manager.join(10)

    status = manager.status()
    assert status["state"] == "completed"
    assert status["active"]["progress"] is None
    assert status["summary"]["done"] == 1


def test_word_counts_are_recorded_for_finished_files(tmp_path):
    manager = JobManager(
        transcriber_factory=FakeTranscriber, transcribe_fn=fake_transcribe_file
    )
    manager.attach(tmp_path / "out")
    audio = make_audio(tmp_path / "audio", "talk.mp3")
    manager.store.add_files(audio)

    manager.start()
    manager.join(10)

    # "hello from talk" + "second segment"
    assert manager.store.get(audio[0])["words"] == 5
