"""Background job manager: independence from callers, resume, failure isolation."""

from __future__ import annotations

import threading
import time
from pathlib import Path

import pytest
from tertius.config import TranscriptionOptions
from tertius.jobs import CANCELLED, COMPLETED, ERROR, JobError, JobManager
from tertius.state import DONE, FAILED, PENDING, StateStore

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio, wait_until


class ManagerHarness:
    """A JobManager wired to a fake model, plus the tertius it built."""

    def __init__(self, output_dir: Path):
        self.tertius: FakeTranscriber | None = None
        self.output_dir = output_dir
        self._pending_gates: dict[str, threading.Event] = {}
        self._pending_failures: set[str] = set()
        self._pending_warmup_error: Exception | None = None
        self.manager = JobManager(
            transcriber_factory=self._factory, transcribe_fn=fake_transcribe_file
        )
        self.manager.attach(output_dir)

    def _factory(self, options):
        # A fresh fake per job, carrying whatever the test asked for.
        self.tertius = FakeTranscriber(options)
        self.tertius.block_paths.update(self._pending_gates)
        self.tertius.fail_paths |= self._pending_failures
        self.tertius.warmup_error = self._pending_warmup_error
        return self.tertius

    def fail(self, *paths):
        self._pending_failures = {str(Path(p).resolve()) for p in paths}

    def block(self, path) -> threading.Event:
        gate = threading.Event()
        self._pending_gates[str(Path(path).resolve())] = gate
        return gate

    def break_model(self, exc: Exception):
        self._pending_warmup_error = exc

    def wait_done(self, timeout: float = 10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.manager.is_running():
                self.manager.join(1)
                return
            time.sleep(0.01)
        raise AssertionError("job did not finish in time")


@pytest.fixture()
def harness(tmp_path):
    h = ManagerHarness(tmp_path / "out")
    yield h
    h.manager.cancel()
    for gate in h._pending_gates.values():
        gate.set()
    h.manager.join(5)


def test_start_returns_immediately_and_work_happens_in_background(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    gate = harness.block(files[0])

    t0 = time.time()
    status = harness.manager.start(files=files)
    elapsed = time.time() - t0

    # The "request" returned while the file is still being transcribed.
    assert elapsed < 1.0
    assert status["running"] is True
    assert harness.manager.is_running() is True

    gate.set()
    harness.wait_done()
    assert harness.manager.status()["state"] == COMPLETED


def test_job_outlives_the_caller_that_started_it(harness, tmp_path):
    """Simulates the browser tab closing: the starting thread goes away."""
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    gate = harness.block(files[0])

    def request_thread():
        harness.manager.start(files=files)

    caller = threading.Thread(target=request_thread)
    caller.start()
    caller.join()  # the "request" is over and its thread is gone

    assert not caller.is_alive()
    assert harness.manager.is_running() is True  # the job is not

    gate.set()
    harness.wait_done()
    summary = harness.manager.status()["summary"]
    assert summary["done"] == 2


def test_status_reflects_real_worker_state(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    gate = harness.block(files[1])
    harness.manager.start(files=files)

    # Poll like the UI does until the worker reaches the blocked second file.
    deadline = time.time() + 10
    while time.time() < deadline:
        status = harness.manager.status()
        if status["current_file"] == str(files[1].resolve()):
            break
        time.sleep(0.01)
    else:
        raise AssertionError("worker never reached the second file")

    assert status["running"] is True
    assert status["state"] == "running"
    assert status["summary"]["done"] == 1
    assert status["summary"]["in_progress"] == 1
    assert status["run"]["processed"] == 1
    assert status["run"]["total"] == 2

    gate.set()
    harness.wait_done()
    final = harness.manager.status()
    assert final["running"] is False
    assert final["current_file"] is None
    assert final["run"] == {
        "total": 2,
        "processed": 2,
        "completed": 2,
        "failed": 0,
        "skipped": 0,
    }


def test_one_failure_does_not_stop_the_batch(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "bad.mp3", "c.mp3")
    harness.fail(files[1])

    harness.manager.start(files=files)
    harness.wait_done()

    status = harness.manager.status()
    assert status["state"] == COMPLETED
    assert status["summary"] == {
        "total": 3,
        "pending": 0,
        "in_progress": 0,
        "done": 2,
        "failed": 1,
        "skipped": 0,
    }
    entry = next(f for f in status["files"] if f["name"] == "bad.mp3")
    assert entry["status"] == FAILED
    assert "simulated decode failure" in entry["error"]
    # The files after the failure still ran.
    assert (harness.output_dir / "c.txt").is_file()


def test_completed_files_are_not_redone_on_resume(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")
    harness.manager.start(files=files[:1])
    harness.wait_done()
    first_pass = list(harness.tertius.calls)

    harness.manager.start(files=files)  # same queue, two new files
    harness.wait_done()

    assert first_pass == [str(files[0].resolve())]
    # Second pass only touched the files that were not already done.
    assert sorted(Path(p).name for p in harness.tertius.calls) == ["b.mp3", "c.mp3"]
    assert harness.manager.status()["run"]["skipped"] == 1


def test_resume_after_interruption_retranscribes_the_in_progress_file(tmp_path):
    """Kill the process mid-file, then resume with a fresh manager."""
    out = tmp_path / "out"
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")

    # Pretend a previous run died: a done, b in-progress, c untouched.
    store = StateStore.for_output_dir(out)
    store.add_files(files)
    store.mark_done(files[0], outputs=[str(out / "a.txt")])
    store.mark_in_progress(files[1])

    harness = ManagerHarness(out)  # attach() resets the interrupted file
    assert harness.manager.status()["can_resume"] is True
    assert harness.manager.store.status_of(files[1]) == PENDING

    harness.manager.resume()
    harness.wait_done()

    assert sorted(Path(p).name for p in harness.tertius.calls) == ["b.mp3", "c.mp3"]
    assert harness.manager.status()["summary"]["done"] == 3
    assert harness.manager.status()["can_resume"] is False


def test_cannot_start_two_jobs_at_once(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    gate = harness.block(files[0])
    harness.manager.start(files=files)

    with pytest.raises(JobError, match="already running"):
        harness.manager.start(files=files)

    gate.set()
    harness.wait_done()


def test_start_with_nothing_pending_raises(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    harness.manager.start(files=files)
    harness.wait_done()

    with pytest.raises(JobError, match="nothing to transcribe"):
        harness.manager.start(files=files)


def test_cancel_stops_the_batch_and_leaves_the_rest_pending(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")
    gate = harness.block(files[0])
    harness.manager.start(files=files)

    # Cancel once the first file is genuinely under way, so we are testing
    # "finish the current file, stop after it" rather than a startup race.
    wait_until(
        lambda: harness.manager.status()["current_file"] == str(files[0].resolve()),
        description="the first file to start",
    )
    harness.manager.cancel()
    gate.set()
    harness.wait_done()

    status = harness.manager.status()
    assert status["state"] == CANCELLED
    assert status["summary"]["done"] == 1
    assert status["summary"]["pending"] == 2
    assert status["can_resume"] is True


def test_model_load_failure_is_a_job_error_not_a_file_error(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    harness.break_model(RuntimeError("no CUDA device"))

    harness.manager.start(files=files)
    harness.wait_done()

    status = harness.manager.status()
    assert status["state"] == ERROR
    assert "no CUDA device" in status["error"]
    # Files stay pending so the user can fix the setting and resume.
    assert status["summary"]["pending"] == 1
    assert status["summary"]["failed"] == 0


def test_retry_failed_reruns_only_failures(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "bad.mp3")
    harness.fail(files[1])
    harness.manager.start(files=files)
    harness.wait_done()
    assert harness.manager.status()["summary"]["failed"] == 1

    harness._pending_failures = set()  # the file is fine this time
    harness.manager.start(retry_failed=True)
    harness.wait_done()

    assert harness.manager.status()["summary"] == {
        "total": 2,
        "pending": 0,
        "in_progress": 0,
        "done": 2,
        "failed": 0,
        "skipped": 0,
    }
    assert [Path(p).name for p in harness.tertius.calls] == ["bad.mp3"]


def test_outputs_are_written_next_to_each_other_named_after_the_source(harness, tmp_path):
    files = make_audio(tmp_path / "audio", "lecture1.mp3")
    harness.manager.start(
        files=files, options=TranscriptionOptions(formats=["txt", "srt"])
    )
    harness.wait_done()

    txt = harness.output_dir / "lecture1.txt"
    srt = harness.output_dir / "lecture1.srt"
    assert txt.is_file() and srt.is_file()
    assert txt.read_text(encoding="utf-8").startswith("hello from lecture1")
    assert "00:00:00,000 --> 00:00:01,500" in srt.read_text(encoding="utf-8")

    entry = harness.manager.store.get(files[0])
    assert entry["status"] == DONE
    assert sorted(Path(p).name for p in entry["outputs"]) == [
        "lecture1.srt",
        "lecture1.txt",
    ]
    assert entry["language"] == "en"


def test_options_persist_into_state_and_reload(tmp_path):
    out = tmp_path / "out"
    files = make_audio(tmp_path / "audio", "a.mp3")
    h1 = ManagerHarness(out)
    h1.manager.start(
        files=files,
        options=TranscriptionOptions(model_size="base", language="fr", formats=["txt"]),
    )
    h1.wait_done()

    h2 = ManagerHarness(out)
    options = h2.manager.status()["options"]
    assert options["model_size"] == "base"
    assert options["language"] == "fr"
    assert options["formats"] == ["txt"]
