"""HTTP layer: routes queue and observe work, they never do the work."""

from __future__ import annotations

import io
import threading
import time
from pathlib import Path

import pytest
from tertius.app import create_app
from tertius.jobs import COMPLETED, JobManager
from tertius.state import StateStore

from .fakes import FakeTranscriber, fake_transcribe_file, make_audio, wait_until


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


def test_index_renders(api):
    res = api.client.get("/")
    assert res.status_code == 200
    assert b"Tertius" in res.data


def test_status_on_a_fresh_install(api):
    body = api.client.get("/api/status").get_json()
    assert body["running"] is False
    assert body["state"] == "idle"
    assert body["files"] == []
    assert body["can_resume"] is False


def test_scan_then_queue(api, tmp_path):
    audio = tmp_path / "audio"
    make_audio(audio, "a.mp3", "b.wav", "notes.txt")
    make_audio(audio / "nested", "c.m4a")

    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    assert scan["count"] == 3  # notes.txt is not media
    assert sorted(Path(f).name for f in scan["files"]) == ["a.mp3", "b.wav", "c.m4a"]

    queued = api.client.post("/api/queue", json={"files": scan["files"]}).get_json()
    assert queued["added"] == 3
    assert queued["status"]["summary"]["pending"] == 3


def test_scan_non_recursive(api, tmp_path):
    audio = tmp_path / "audio"
    make_audio(audio, "a.mp3")
    make_audio(audio / "nested", "c.m4a")
    scan = api.client.post(
        "/api/scan", json={"directory": str(audio), "recursive": False}
    ).get_json()
    assert [Path(f).name for f in scan["files"]] == ["a.mp3"]


def test_scan_rejects_a_bad_directory(api, tmp_path):
    res = api.client.post("/api/scan", json={"directory": str(tmp_path / "nope")})
    assert res.status_code == 404
    assert "not a directory" in res.get_json()["error"]


def test_queue_rejects_missing_files(api, tmp_path):
    res = api.client.post("/api/queue", json={"files": [str(tmp_path / "ghost.mp3")]})
    assert res.status_code == 404


def test_upload_saves_and_queues(api):
    """.txt files are kept as possible reference texts, not rejected;
    anything else still is."""
    data = {
        "files": [
            (io.BytesIO(b"\x00fake"), "talk.mp3"),
            (io.BytesIO(b"nope"), "readme.txt"),
            (io.BytesIO(b"nope"), "handout.pdf"),
        ]
    }
    res = api.client.post(
        "/api/upload", data=data, content_type="multipart/form-data"
    ).get_json()

    assert [Path(p).name for p in res["saved"]] == ["talk.mp3"]
    assert [Path(p).name for p in res["texts"]] == ["readme.txt"]
    assert res["rejected"] == ["handout.pdf"]
    assert res["status"]["summary"]["pending"] == 1  # only the audio is queued


def test_start_returns_while_the_job_is_still_running(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    gate = api.block(files[0])

    res = api.client.post(
        "/api/job/start",
        json={"files": [str(f) for f in files], "options": {"model_size": "tiny"}},
    )

    # The HTTP request completed; the batch has not.
    assert res.status_code == 200
    assert res.get_json()["running"] is True
    assert api.manager.is_running() is True

    # A second, independent request sees live progress.
    status = api.client.get("/api/status").get_json()
    assert status["running"] is True
    assert status["options"]["model_size"] == "tiny"

    gate.set()
    api.wait_done()
    assert api.client.get("/api/status").get_json()["state"] == COMPLETED


def test_job_survives_the_client_going_away(api, tmp_path):
    """Drop the test client entirely mid-job — the worker must not care."""
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    gate = api.block(files[0])
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})

    api.client = None  # the browser tab is gone
    assert api.manager.is_running() is True

    gate.set()
    api.wait_done()

    # A brand-new client reconnects to the finished job's state.
    fresh = api.app.test_client()
    status = fresh.get("/api/status").get_json()
    assert status["state"] == COMPLETED
    assert status["summary"]["done"] == 2


def test_starting_twice_conflicts(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    gate = api.block(files[0])
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})

    res = api.client.post("/api/job/start", json={"files": [str(f) for f in files]})
    assert res.status_code == 409
    assert "already running" in res.get_json()["error"]

    gate.set()
    api.wait_done()


def test_start_with_invalid_options_is_rejected(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    res = api.client.post(
        "/api/job/start",
        json={"files": [str(f) for f in files], "options": {"model_size": "enormous"}},
    )
    assert res.status_code == 400
    assert "unknown model size" in res.get_json()["error"]
    assert api.manager.is_running() is False


def test_resume_endpoint_picks_up_a_previous_run(tmp_path):
    out = tmp_path / "out"
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")

    # A previous process died with b.mp3 in progress.
    store = StateStore.for_output_dir(out)
    store.add_files(files)
    store.mark_done(files[0], outputs=[str(out / "a.txt")])
    store.mark_in_progress(files[1])

    api = ApiHarness(tmp_path)  # startup attaches and offers a resume
    status = api.client.get("/api/status").get_json()
    assert status["can_resume"] is True
    assert status["summary"]["pending"] == 1

    api.client.post("/api/job/resume", json={})
    api.wait_done()

    assert [Path(p).name for p in api.tertius.calls] == ["b.mp3"]
    final = api.client.get("/api/status").get_json()
    assert final["summary"]["done"] == 2
    assert final["can_resume"] is False


def test_cancel_endpoint(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3")
    gate = api.block(files[0])
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})
    wait_until(
        lambda: api.client.get("/api/status").get_json()["current_file"],
        description="the first file to start",
    )

    res = api.client.post("/api/job/cancel", json={}).get_json()
    assert res["cancel_requested"] is True

    gate.set()
    api.wait_done()
    status = api.client.get("/api/status").get_json()
    assert status["state"] == "cancelled"
    assert status["summary"]["pending"] == 2


def test_retry_failed_endpoint(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})
    api.wait_done()
    api.manager.store.mark_failed(files[0], "boom")

    res = api.client.post("/api/job/retry-failed", json={}).get_json()
    assert res["retried"] == 1
    assert res["status"]["summary"]["pending"] == 1


def test_retrying_one_file_leaves_the_other_failure_alone(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})
    api.wait_done()
    for path in files:
        api.manager.store.mark_failed(path, "boom")

    res = api.client.post("/api/queue/retry", json={"path": str(files[0])})

    assert res.status_code == 200
    assert api.manager.store.status_of(files[0]) == "pending"
    assert api.manager.store.status_of(files[1]) == "failed"


def test_only_a_failed_file_can_be_retried(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3")
    api.client.post("/api/queue", json={"files": [str(f) for f in files]})

    res = api.client.post("/api/queue/retry", json={"path": str(files[0])})

    assert res.status_code == 409
    assert api.manager.store.status_of(files[0]) == "pending"


def test_retrying_a_file_that_is_not_queued_is_a_404(api, tmp_path):
    res = api.client.post("/api/queue/retry", json={"path": str(tmp_path / "gone.mp3")})
    assert res.status_code == 404


def test_open_output_hands_the_folder_to_the_desktop(api, monkeypatch):
    opened = []
    # Never actually spawn a file manager during a test run.
    monkeypatch.setattr("tertius.app.sys.platform", "win32")
    monkeypatch.setattr("tertius.app.os.startfile", opened.append, raising=False)

    res = api.client.post("/api/open-output", json={})

    assert res.status_code == 200
    assert opened == [str(api.output_dir.resolve())]


def test_queue_remove_is_blocked_while_running(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    gate = api.block(files[0])
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})

    res = api.client.post("/api/queue/remove", json={"path": str(files[1])})
    assert res.status_code == 409

    gate.set()
    api.wait_done()
    assert api.client.post(
        "/api/queue/remove", json={"path": str(files[1])}
    ).get_json()["removed"] is True


def test_transcript_download(api, tmp_path):
    files = make_audio(tmp_path / "audio", "talk.mp3")
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})
    api.wait_done()

    res = api.client.get("/api/transcript?name=talk.txt")
    assert res.status_code == 200
    assert b"hello from talk" in res.data

    missing = api.client.get("/api/transcript?name=ghost.txt")
    assert missing.status_code == 404


@pytest.mark.parametrize(
    "name", ["../secret.txt", "..%2Fsecret.txt", "nested/../../secret.txt"]
)
def test_transcript_cannot_escape_the_output_dir(api, tmp_path, name):
    (tmp_path / "secret.txt").write_text("private", encoding="utf-8")
    res = api.client.get("/api/transcript", query_string={"name": name})
    assert res.status_code in (403, 404)
    assert b"private" not in res.data
