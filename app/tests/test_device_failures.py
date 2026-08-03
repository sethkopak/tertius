"""Behaviour when the GPU is broken or a file wedges the model.

All of this comes from one real incident: a machine with an NVIDIA driver (so
CTranslate2 reported a CUDA device) but no CUDA runtime libraries. The model
loaded, the first file failed at `encode` with "Library cublas64_12.dll is not
found", and the *next* file hung inside native code where cancel could never
reach it.
"""

from __future__ import annotations

import threading

import pytest
from tertius import transcribe
from tertius.config import TranscriptionOptions
from tertius.jobs import ERROR, REPEATED_FAILURE_LIMIT, JobManager
from tertius.state import FAILED, PENDING
from tertius.transcribe import GpuUnavailableError, WhisperTranscriber

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio, wait_until

CUBLAS_ERROR = "Library cublas64_12.dll is not found or cannot be loaded"


class FakeModel:
    """A model that loads fine and fails (or not) when actually used."""

    def __init__(self, device, fail_on_use=None):
        self.device = device
        self.fail_on_use = fail_on_use
        self.transcribe_calls = 0

    def transcribe(self, audio, **kwargs):
        self.transcribe_calls += 1
        if self.fail_on_use:
            raise RuntimeError(self.fail_on_use)

        def segments():
            return iter(())

        return segments(), object()


@pytest.fixture(autouse=True)
def forget_cuda_failures():
    """Each test starts with a clean slate; the flag is process-wide."""
    transcribe.reset_cuda_state()
    yield
    transcribe.reset_cuda_state()


def build_transcriber(monkeypatch, device, cuda_devices=1, gpu_error=CUBLAS_ERROR):
    """A WhisperTranscriber whose model construction we control."""
    built = []

    def fake_build(self, target):
        model = FakeModel(
            target, fail_on_use=gpu_error if target == "cuda" else None
        )
        built.append(model)
        return model

    monkeypatch.setattr(WhisperTranscriber, "_build", fake_build)
    monkeypatch.setattr(
        transcribe, "register_cuda_dll_directories", lambda: [], raising=False
    )

    import sys
    import types

    fake_ct2 = types.ModuleType("ctranslate2")
    fake_ct2.get_cuda_device_count = lambda: cuda_devices
    monkeypatch.setitem(sys.modules, "ctranslate2", fake_ct2)

    return WhisperTranscriber(TranscriptionOptions(device=device)), built


def test_auto_falls_back_to_cpu_when_the_gpu_cannot_actually_run(monkeypatch):
    """A CUDA *device* existing is not the same as CUDA *working*."""
    transcriber, built = build_transcriber(monkeypatch, "auto")

    transcriber.warmup()

    assert transcriber.active_device == "cpu"
    assert CUBLAS_ERROR in transcriber.gpu_fallback_reason
    assert [m.device for m in built] == ["cuda", "cpu"]  # tried GPU, then fell back


def test_auto_uses_the_gpu_when_it_works(monkeypatch):
    transcriber, built = build_transcriber(monkeypatch, "auto", gpu_error=None)

    transcriber.warmup()

    assert transcriber.active_device == "cuda"
    assert transcriber.gpu_fallback_reason is None
    assert [m.device for m in built] == ["cuda"]


def test_auto_goes_straight_to_cpu_with_no_cuda_device(monkeypatch):
    transcriber, built = build_transcriber(monkeypatch, "auto", cuda_devices=0)

    transcriber.warmup()

    assert transcriber.active_device == "cpu"
    assert [m.device for m in built] == ["cpu"]


def test_explicitly_choosing_cuda_fails_loudly_instead_of_falling_back(monkeypatch):
    """Silently using the CPU would be a nasty surprise on a 40-hour batch."""
    transcriber, _built = build_transcriber(monkeypatch, "cuda")

    with pytest.raises(GpuUnavailableError) as caught:
        transcriber.warmup()

    assert CUBLAS_ERROR in str(caught.value)
    assert "nvidia-cublas-cu12" in str(caught.value)  # tells them how to fix it
    assert "Device to cpu" in str(caught.value)


def test_the_device_is_proved_by_running_the_model_not_just_loading_it(monkeypatch):
    """Loading on CUDA succeeds even when CUDA is unusable; only a real encode
    surfaces it."""
    transcriber, built = build_transcriber(monkeypatch, "auto", gpu_error=None)
    transcriber.warmup()
    assert built[0].transcribe_calls == 1


def test_a_failed_gpu_is_never_retried_in_this_process(monkeypatch):
    """Retrying CUDA after it has failed once can deadlock in native code rather
    than raise - which is how a whole batch came to hang. So the first failure
    is remembered and the GPU is not touched again."""
    first, built = build_transcriber(monkeypatch, "auto")
    first.warmup()
    assert first.active_device == "cpu"
    attempts_after_first = [m.device for m in built]

    second, built2 = build_transcriber(monkeypatch, "auto")
    second.warmup()

    assert attempts_after_first == ["cuda", "cpu"]
    assert [m.device for m in built2] == ["cpu"]  # never touched CUDA again
    assert second.active_device == "cpu"
    assert CUBLAS_ERROR in second.gpu_fallback_reason


def test_explicit_cuda_fails_fast_once_the_gpu_is_known_broken(monkeypatch):
    first, _ = build_transcriber(monkeypatch, "auto")
    first.warmup()  # records the failure

    second, built = build_transcriber(monkeypatch, "cuda")
    with pytest.raises(GpuUnavailableError) as caught:
        second.warmup()

    assert built == []  # raised without constructing anything on the GPU
    assert CUBLAS_ERROR in str(caught.value)


class ExplodingTranscriber(FakeTranscriber):
    """Every file fails the same way, as with a broken CUDA install."""

    def __init__(self, options, on_download_progress=None):
        super().__init__(options)
        self.error = RuntimeError(CUBLAS_ERROR)

    def transcribe(self, path):
        self.calls.append(str(path))
        raise self.error


def test_the_same_error_on_every_file_stops_the_batch(tmp_path):
    """Grinding through 200 files to fail all 200 identically helps nobody."""
    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: (
            ExplodingTranscriber(options)
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    files = make_audio(tmp_path / "audio", *[f"f{i}.mp3" for i in range(10)])

    manager.start(files=files)
    manager.join(20)

    status = manager.status()
    assert status["state"] == ERROR
    assert status["summary"][FAILED] == REPEATED_FAILURE_LIMIT
    # Everything else is left pending, not burned through.
    assert status["summary"][PENDING] == 10 - REPEATED_FAILURE_LIMIT
    assert "files in a row failed with the same error" in status["error"]
    assert CUBLAS_ERROR in status["error"]


def test_different_errors_do_not_stop_the_batch(tmp_path):
    """The original rule still holds: one bad file is just one bad file."""

    class VariedFailures(FakeTranscriber):
        def __init__(self, options, on_download_progress=None):
            super().__init__(options)

        def transcribe(self, path):
            self.calls.append(str(path))
            raise RuntimeError(f"unique problem with {path}")

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: (
            VariedFailures(options)
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    files = make_audio(tmp_path / "audio", *[f"f{i}.mp3" for i in range(6)])

    manager.start(files=files)
    manager.join(20)

    status = manager.status()
    assert status["summary"][FAILED] == 6  # all attempted
    assert status["state"] != ERROR


def test_cancel_reports_how_long_it_has_been_waiting(tmp_path):
    """The bug: a wedged file left the UI on "CANCELLING" with no explanation."""
    gate = threading.Event()

    def factory(options, on_download_progress=None):
        transcriber = FakeTranscriber(options)
        return transcriber

    manager = JobManager(transcriber_factory=factory, transcribe_fn=fake_transcribe_file)
    manager.attach(tmp_path / "out")
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")

    def block_forever(transcriber, source, output_dir):
        gate.wait(timeout=30)
        return fake_transcribe_file(transcriber, source, output_dir)

    manager._transcribe_fn = block_forever
    manager.start(files=files)
    wait_until(lambda: manager.status()["current_file"], description="the first file")

    manager.cancel()
    status = manager.status()
    assert status["cancel_requested"] is True
    assert status["running"] is True
    assert status["cancel_pending_seconds"] is not None
    # Not yet stuck - it has only just been asked.
    assert status["force_stop_suggested"] is False

    # Once the wait exceeds our patience, the UI is told to offer a force stop.
    # The clock is wound back rather than raced: with patience=0 this needs a
    # strictly positive elapsed time, and time.time() only gained sub-millisecond
    # resolution on Windows in Python 3.13 - below that the elapsed time here can
    # still read as exactly 0.0. Caught by CI on windows/3.11.
    manager._cancel_requested_at -= 30
    assert manager.force_stop_is_the_only_way_out(patience=20) is True

    gate.set()
    manager.join(10)
    assert manager.status()["cancel_pending_seconds"] is None


def test_cpu_fallback_is_surfaced_to_the_user(tmp_path):
    """Running many times slower on the CPU should never be silent."""

    class FellBack(FakeTranscriber):
        def __init__(self, options, on_download_progress=None):
            super().__init__(options)
            self.active_device = "cpu"
            self.gpu_fallback_reason = CUBLAS_ERROR

    gate = threading.Event()

    def wait_then_transcribe(transcriber, source, output_dir):
        gate.wait(timeout=30)
        return fake_transcribe_file(transcriber, source, output_dir)

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FellBack(options),
        transcribe_fn=wait_then_transcribe,
    )
    manager.attach(tmp_path / "out")
    manager.start(files=make_audio(tmp_path / "audio", "a.mp3"))

    wait_until(lambda: manager.status()["notice"], description="the fallback notice")
    status = manager.status()
    assert status["active_device"] == "cpu"
    assert "could not be used" in status["notice"]
    assert CUBLAS_ERROR in status["notice"]

    gate.set()
    manager.join(10)
    assert manager.status()["summary"]["done"] == 1
