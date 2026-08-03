"""Clearing the queue.

The one destructive action in the app, so the rules matter: it forgets what was
lined up, it never touches a transcript already written, and it refuses while a
job is running.
"""

from __future__ import annotations

from tertius.state import StateStore

from .fakes import make_audio


def test_clearing_empties_the_queue(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(make_audio(tmp_path / "audio", "a.mp3", "b.mp3", "c.mp3"))

    assert store.clear() == 3
    assert store.snapshot()["files"] == []
    assert store.summary()["total"] == 0


def test_clearing_an_empty_queue_is_a_no_op(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")

    assert store.clear() == 0


def test_clearing_keeps_the_settings(tmp_path):
    """Forgetting the list is not the same as wanting the model reset."""
    store = StateStore.for_output_dir(tmp_path / "out")
    store.set_context(tmp_path / "out", {"model_size": "small", "language": "es"})
    store.add_files(make_audio(tmp_path / "audio", "a.mp3"))

    store.clear()

    assert store.snapshot()["options"]["model_size"] == "small"
    assert store.snapshot()["options"]["language"] == "es"


def test_clearing_leaves_written_transcripts_alone(tmp_path):
    """The queue is a to-do list, not the work itself."""
    out = tmp_path / "out"
    store = StateStore.for_output_dir(out)
    store.add_files(make_audio(tmp_path / "audio", "a.mp3"))
    transcript = out / "a.txt"
    transcript.write_text("the transcript", encoding="utf-8")

    store.clear()

    assert transcript.read_text(encoding="utf-8") == "the transcript"


def test_the_endpoint_clears_and_reports(api, tmp_path):
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    api.client.post("/api/queue", json={"files": [str(f) for f in files]})

    res = api.client.post("/api/queue/clear", json={})

    assert res.status_code == 200
    assert res.get_json()["cleared"] == 2
    assert res.get_json()["status"]["summary"]["total"] == 0


def test_the_endpoint_refuses_while_a_job_is_running(api, tmp_path):
    """Pulling the list out from under the worker is not something you meant."""
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    gate = api.block(files[0])
    api.client.post("/api/job/start", json={"files": [str(f) for f in files]})

    res = api.client.post("/api/queue/clear", json={})

    assert res.status_code == 409
    assert "running" in res.get_json()["error"]

    gate.set()
    api.wait_done()
    assert api.client.post("/api/queue/clear", json={}).status_code == 200


def test_clearing_also_removes_the_uploaded_copies(api, tmp_path):
    """Nothing will refer to them again once the queue that named them is gone."""
    from tertius.config import UPLOAD_DIRNAME

    uploads = api.output_dir / UPLOAD_DIRNAME
    uploads.mkdir(parents=True, exist_ok=True)
    uploaded = uploads / "dragged-in.mp3"
    uploaded.write_bytes(b"\x00" * 2048)
    api.client.post("/api/queue", json={"files": [str(uploaded)]})

    res = api.client.post("/api/queue/clear", json={})

    assert not uploaded.exists()
    assert res.get_json()["uploads_removed"] == 1
    assert res.get_json()["bytes_reclaimed"] == 2048
