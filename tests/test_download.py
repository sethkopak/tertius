"""Model download reporting: progress aggregation and the job's download phase."""

from __future__ import annotations

import pytest
from tertius import transcribe
from tertius.config import TranscriptionOptions
from tertius.jobs import DOWNLOADING_MODEL, LOADING_MODEL, TRANSCRIBING, JobManager

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio, wait_until


class FakeTqdm:
    """Stand-in for tqdm.auto.tqdm, which the real class subclasses.

    Mirrors the real thing where it matters: `n` accumulates, and `total` is a
    plain attribute that huggingface_hub is free to change later.
    """

    def __init__(self, *args, **kwargs):
        self.total = kwargs.get("total")
        self.n = 0

    def update(self, n=1):
        self.n += n
        return True


@pytest.fixture()
def fake_tqdm(monkeypatch):
    import sys
    import types

    module = types.ModuleType("tqdm.auto")
    module.tqdm = FakeTqdm
    monkeypatch.setitem(sys.modules, "tqdm.auto", module)
    return module


def test_progress_sums_concurrent_file_downloads(fake_tqdm):
    """huggingface_hub downloads several files at once, one bar each."""
    seen = []
    cls = transcribe._progress_tqdm_class(lambda done, total: seen.append((done, total)))

    a = cls(total=100, unit="B")
    b = cls(total=300, unit="B")
    a.update(50)
    b.update(150)
    a.update(50)

    assert seen[-1] == (250, 400)


def test_non_byte_bars_are_ignored(fake_tqdm):
    """The "Fetching 3 files" bar must not pollute the byte totals."""
    seen = []
    cls = transcribe._progress_tqdm_class(lambda done, total: seen.append((done, total)))

    files_bar = cls(total=3, unit="it")
    bytes_bar = cls(total=1000, unit="B")
    files_bar.update(1)
    bytes_bar.update(400)

    assert seen[-1] == (400, 1000)


def test_total_is_read_live_because_hub_grows_it(fake_tqdm):
    """Regression: huggingface_hub 1.x creates a byte bar with no total and
    raises it as the download is sized. Capturing total in __init__ left the UI
    stuck at 0% forever."""
    seen = []
    cls = transcribe._progress_tqdm_class(lambda done, total: seen.append((done, total)))

    bar = cls(total=None, unit="B")  # no total yet
    bar.update(1000)
    assert seen[-1] == (1000, 0)  # honest: bytes so far, total unknown

    bar.total = 150_000_000  # the hub fills it in...
    bar.update(500)
    assert seen[-1] == (1500, 150_000_000)

    bar.total = 148_000_000  # ...and can revise it
    bar.update(500)
    assert seen[-1] == (2000, 148_000_000)


def test_untotalled_bars_do_not_dilute_a_real_total(fake_tqdm):
    """The open-ended counter and the sized bar track the same bytes; counting
    both would double the denominator."""
    seen = []
    cls = transcribe._progress_tqdm_class(lambda done, total: seen.append((done, total)))

    open_ended = cls(total=None, unit="B")
    sized = cls(total=1000, unit="B")
    open_ended.update(400)
    sized.update(400)

    assert seen[-1] == (400, 1000)


def test_progress_never_exceeds_the_total(fake_tqdm):
    seen = []
    cls = transcribe._progress_tqdm_class(lambda done, total: seen.append((done, total)))
    bar = cls(total=1000, unit="B")
    bar.update(1200)
    assert seen[-1] == (1000, 1000)


def test_ensure_model_downloaded_passes_the_right_patterns(monkeypatch):
    captured = {}

    def fake_snapshot_download(repo_id, **kwargs):
        captured["repo_id"] = repo_id
        captured["kwargs"] = kwargs
        return "C:/cache/model"

    monkeypatch.setattr(
        "huggingface_hub.snapshot_download", fake_snapshot_download, raising=False
    )
    path = transcribe.ensure_model_downloaded("some-org/some-model")

    assert path == "C:/cache/model"
    assert captured["repo_id"] == "some-org/some-model"
    assert captured["kwargs"]["allow_patterns"] == transcribe.MODEL_FILE_PATTERNS
    assert "tqdm_class" not in captured["kwargs"]  # no callback given


def test_repo_id_resolution_rejects_unknown_models():
    pytest.importorskip("faster_whisper")
    assert transcribe.resolve_repo_id("large-v3-turbo").endswith(
        "faster-whisper-large-v3-turbo"
    )
    assert transcribe.resolve_repo_id("org/custom-ct2") == "org/custom-ct2"
    with pytest.raises(ValueError, match="unknown model"):
        transcribe.resolve_repo_id("gigantic")


class DownloadingTranscriber(FakeTranscriber):
    """Reports fake download progress during warmup, like a real first run."""

    def __init__(self, options, on_download_progress=None):
        super().__init__(options)
        self.on_download_progress = on_download_progress
        self.progress_gate = None

    def warmup(self):
        if self.progress_gate is not None:
            self.progress_gate.wait(timeout=10)
        if self.on_download_progress:
            self.on_download_progress(500, 1000)
        super().warmup()


def test_status_reports_the_download_phase(tmp_path, monkeypatch):
    import threading

    monkeypatch.setattr(JobManager, "_model_is_cached", staticmethod(lambda size: False))
    built = {}
    gate = threading.Event()

    def factory(options, on_download_progress=None):
        t = DownloadingTranscriber(options, on_download_progress)
        t.progress_gate = gate
        built["transcriber"] = t
        return t

    manager = JobManager(transcriber_factory=factory, transcribe_fn=fake_transcribe_file)
    manager.attach(tmp_path / "out")
    files = make_audio(tmp_path / "audio", "a.mp3")
    manager.start(files=files, options=TranscriptionOptions(model_size="large-v3-turbo"))

    # Warmup is blocked, so the job parks in the download phase and stays there.
    wait_until(
        lambda: manager.status()["phase"] == DOWNLOADING_MODEL,
        description="the download phase",
    )
    status = manager.status()
    assert status["running"] is True
    assert status["download"]["model"] == "large-v3-turbo"
    # The size shown to the user is the measured one, not the hub's inflated total.
    assert status["download"]["expected_bytes"] == 1_621_665_983

    gate.set()
    for _ in range(500):
        if not manager.is_running():
            break
        import time

        time.sleep(0.01)
    manager.join(5)

    assert built["transcriber"].warmed_up is True
    assert manager.status()["phase"] is None  # cleared when the job ends


def test_cached_model_reports_loading_not_downloading(tmp_path, monkeypatch):
    monkeypatch.setattr(JobManager, "_model_is_cached", staticmethod(lambda size: True))
    phases = []

    def factory(options, on_download_progress=None):
        phases.append(manager.status()["phase"])
        return FakeTranscriber(options)

    manager = JobManager(
        transcriber_factory=factory, transcribe_fn=fake_transcribe_file
    )
    manager.attach(tmp_path / "out")
    files = make_audio(tmp_path / "audio", "a.mp3")
    manager.start(files=files)
    manager.join(10)

    status = manager.status()
    assert status["summary"]["done"] == 1
    assert status["phase"] is None
    assert DOWNLOADING_MODEL not in phases


def test_phase_becomes_transcribing_after_warmup(tmp_path, monkeypatch):
    monkeypatch.setattr(JobManager, "_model_is_cached", staticmethod(lambda size: True))
    import threading

    gate = threading.Event()
    seen = {}

    def transcribe_fn(transcriber, source, output_dir):
        seen["phase"] = manager.status()["phase"]
        gate.set()
        return fake_transcribe_file(transcriber, source, output_dir)

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=transcribe_fn,
    )
    manager.attach(tmp_path / "out")
    manager.start(files=make_audio(tmp_path / "audio", "a.mp3"))
    gate.wait(timeout=10)
    manager.join(10)

    assert seen["phase"] == TRANSCRIBING


def test_a_factory_without_the_progress_argument_still_works(tmp_path):
    """Older/simpler factories (and test doubles) must not break."""
    manager = JobManager(
        transcriber_factory=lambda options: FakeTranscriber(options),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(tmp_path / "out")
    manager.start(files=make_audio(tmp_path / "audio", "a.mp3"))
    manager.join(10)
    assert manager.status()["summary"]["done"] == 1


def test_loading_phase_constant_is_used_for_cached_models():
    assert (DOWNLOADING_MODEL, LOADING_MODEL) == ("downloading_model", "loading_model")
