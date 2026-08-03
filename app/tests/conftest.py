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

from .fakes import FakeTranscriber, fake_transcribe_file  # noqa: E402


class ApiHarness:
    def __init__(self, tmp_path: Path):
        self.output_dir = tmp_path / "out"
        self.tertius: FakeTranscriber | None = None
        self.gates: dict[str, threading.Event] = {}
        self.manager = JobManager(
            transcriber_factory=self._factory, transcribe_fn=fake_transcribe_file
        )
        self.app = create_app(self.output_dir, manager=self.manager)
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def _factory(self, options):
        self.tertius = FakeTranscriber(options)
        self.tertius.block_paths.update(self.gates)
        return self.tertius

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
