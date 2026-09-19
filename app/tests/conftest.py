"""Make `src/` importable without an editable install, and share the harness."""

import sys
import threading
import time
from pathlib import Path

import pytest

SRC = Path(__file__).resolve().parents[1] / "src"
if str(SRC) not in sys.path:
    sys.path.insert(0, str(SRC))

from tertius.app import create_app  # noqa: E402 - needs the path set above
from tertius.jobs import JobManager  # noqa: E402

from .fakes import (  # noqa: E402
    FakeSpeaker,
    FakeTranscriber,
    FakeTranslator,
    fake_transcribe_file,
)


class ApiHarness:
    def __init__(self, tmp_path: Path):
        self.output_dir = tmp_path / "out"
        self.tertius: FakeTranscriber | None = None
        self.translator: FakeTranslator | None = None
        # Set before starting a job; the translator is not built until then.
        self.translator_fails = False
        self.translator_load_error: Exception | None = None
        self.translator_prepare_error: Exception | None = None
        self.speaker: FakeSpeaker | None = None
        self.speaker_fails = False
        self.speaker_load_error: Exception | None = None
        self.speaker_prepare_error: Exception | None = None
        self.speaker_speak_error: Exception | None = None
        self.cpu_only = False
        self.gates: dict[str, threading.Event] = {}
        self.manager = JobManager(
            transcriber_factory=self._factory,
            transcribe_fn=fake_transcribe_file,
            translator_factory=self._translator_factory,
            speaker_factory=self._speaker_factory,
        )
        self.app = create_app(self.output_dir, manager=self.manager)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _factory(self, options):
        self.tertius = FakeTranscriber(options)
        self.tertius.block_paths.update(self.gates)
        return self.tertius

    def _translator_factory(self, model_key, device="auto", on_download_progress=None):
        self.translator = FakeTranslator(model_key, device, on_download_progress)
        self.translator.fail_always = self.translator_fails
        self.translator.load_error = self.translator_load_error
        self.translator.prepare_error = self.translator_prepare_error
        return self.translator

    def _speaker_factory(self, model_key, device="auto", on_download_progress=None):
        self.speaker = FakeSpeaker(model_key, device, on_download_progress)
        self.speaker.fail_always = self.speaker_fails
        self.speaker.load_error = self.speaker_load_error
        self.speaker.prepare_error = self.speaker_prepare_error
        self.speaker.speak_error = self.speaker_speak_error
        return self.speaker

    def block(self, path) -> threading.Event:
        gate = threading.Event()
        self.gates[str(Path(path).resolve())] = gate
        return gate

    def wait_done(self, timeout: float = 10.0):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if not self.manager.is_running():
                self.manager.join(1)
                return
            time.sleep(0.01)
        raise AssertionError("job did not finish in time")


@pytest.fixture()
def api(tmp_path):
    h = ApiHarness(tmp_path)
    yield h
    h.manager.cancel()
    for gate in h.gates.values():
        gate.set()
    h.manager.join(5)


@pytest.fixture(autouse=True)
def isolated_session_file(tmp_path, monkeypatch):
    """Keep the suite out of the real remembered-settings file.

    Attaching to an output directory records it as "where I was last", and the
    tests attach constantly - to temporary folders that are gone by the time
    anyone launches Tertius. Without this, running the suite would repoint the
    app at a deleted directory.
    """
    monkeypatch.setenv("TERTIUS_SESSION_FILE", str(tmp_path / "session.json"))
