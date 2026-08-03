"""Uploading audio with its text, and toggling the feature after queueing.

Both of these were reported broken: an uploaded file always showed "transcribe"
with no sign of whether its text had been found, because uploads never ran the
matching at all and .txt uploads were deleted as "rejected".
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from tertius.state import (
    MODE_ALIGN,
    MODE_TRANSCRIBE,
    MODE_UNDECIDED,
    StateStore,
)

from .fakes import make_audio
from .test_api import ApiHarness  # noqa: F401  (fixture machinery)


@pytest.fixture()
def api(tmp_path):
    from .test_api import ApiHarness as Harness

    harness = Harness(tmp_path)
    yield harness
    harness.manager.cancel()
    harness.manager.join(5)


def upload(api, files, match=True):
    data = {"files": files, "match_reference_text": "1" if match else "0"}
    return api.client.post(
        "/api/upload", data=data, content_type="multipart/form-data"
    ).get_json()


def test_uploaded_text_file_is_kept_not_rejected(api):
    result = upload(
        api,
        [
            (io.BytesIO(b"\x00fake"), "V1_01.mp3"),
            (io.BytesIO("The spoken words.".encode()), "V1_01.txt"),
        ],
    )

    assert [Path(p).name for p in result["saved"]] == ["V1_01.mp3"]
    assert [Path(p).name for p in result["texts"]] == ["V1_01.txt"]
    assert result["rejected"] == []


def test_uploaded_audio_is_paired_with_its_uploaded_text(api):
    """The reported bug: this used to come back as plain "transcribe"."""
    result = upload(
        api,
        [
            (io.BytesIO(b"\x00fake"), "V1_01.mp3"),
            (io.BytesIO("The spoken words.".encode()), "V1_01.txt"),
        ],
    )

    assert result["matched_text"] == 1
    assert result["needs_choice"] == 0
    entry = next(f for f in result["status"]["files"] if f["name"] == "V1_01.mp3")
    assert entry["mode"] == MODE_ALIGN
    assert Path(entry["reference_text"]).name == "V1_01.txt"


def test_upload_order_does_not_matter(api):
    """Text first, audio second must work the same."""
    result = upload(
        api,
        [
            (io.BytesIO("The spoken words.".encode()), "V1_02.txt"),
            (io.BytesIO(b"\x00fake"), "V1_02.mp3"),
        ],
    )
    assert result["matched_text"] == 1


def test_uploaded_audio_without_text_asks_rather_than_assuming(api):
    result = upload(api, [(io.BytesIO(b"\x00fake"), "lonely.mp3")])

    assert result["needs_choice"] == 1
    entry = result["status"]["files"][0]
    assert entry["mode"] == MODE_UNDECIDED


def test_upload_without_the_feature_on_still_just_transcribes(api):
    result = upload(api, [(io.BytesIO(b"\x00fake"), "plain.mp3")], match=False)
    assert result["status"]["files"][0]["mode"] == MODE_TRANSCRIBE
    assert result["needs_choice"] == 0


def test_a_real_junk_file_is_still_rejected(api):
    result = upload(api, [(io.BytesIO(b"nope"), "notes.pdf")])
    assert result["rejected"] == ["notes.pdf"]


def test_toggling_the_option_re_evaluates_what_is_already_queued(tmp_path):
    """Ticking the box after queueing used to do nothing at all."""
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "a.mp3", "b.mp3")
    (audio_dir / "a.txt").write_text("words", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(files)  # queued with the feature off
    assert store.get(files[0])["mode"] == MODE_TRANSCRIBE

    matched, undecided, reverted = store.apply_reference_mode(True)

    assert (matched, undecided, reverted) == (1, 1, 0)
    assert store.get(files[0])["mode"] == MODE_ALIGN
    assert store.get(files[1])["mode"] == MODE_UNDECIDED


def test_turning_the_option_off_puts_everything_back(tmp_path):
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "a.mp3", "b.mp3")
    (audio_dir / "a.txt").write_text("words", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(files, match_reference_text=True)

    matched, undecided, reverted = store.apply_reference_mode(False)

    assert reverted == 2
    assert store.get(files[0])["mode"] == MODE_TRANSCRIBE
    assert store.get(files[1])["mode"] == MODE_TRANSCRIBE
    assert store.files_needing_a_decision() == []


def test_toggling_does_not_disturb_finished_or_skipped_files(tmp_path):
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "done.mp3", "skipped.mp3", "pending.mp3")
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(files)
    store.mark_done(files[0], outputs=["done.txt"])
    store.set_mode(files[1], "skip")

    store.apply_reference_mode(True)

    assert store.get(files[0])["mode"] == MODE_TRANSCRIBE  # already finished
    assert store.get(files[1])["mode"] == "skip"  # deliberate choice kept
    assert store.get(files[2])["mode"] == MODE_UNDECIDED


def test_picker_cli_chooses_a_file_or_a_folder(monkeypatch):
    """`--file` must reach the file dialog, not the folder one."""
    from tertius import folder_picker

    calls = []
    monkeypatch.setattr(
        folder_picker, "pick_folder", lambda d=None: calls.append(("folder", d)) or ""
    )
    monkeypatch.setattr(
        folder_picker, "pick_text_file", lambda d=None: calls.append(("file", d)) or ""
    )

    folder_picker.main([])
    folder_picker.main(["--file"])
    folder_picker.main(["--file", "C:/start/here"])

    assert calls == [
        ("folder", None),
        ("file", None),
        ("file", "C:/start/here"),
    ]


def test_attaching_a_text_file_by_hand(api, tmp_path):
    """The manual route, for when names do not match."""
    files = make_audio(tmp_path / "audio", "recording.mp3")
    manual = tmp_path / "somewhere" / "different-name.txt"
    manual.parent.mkdir()
    manual.write_text("the words", encoding="utf-8")
    api.client.post("/api/queue", json={"files": [str(f) for f in files]})

    res = api.client.post(
        "/api/queue/mode",
        json={"path": str(files[0]), "mode": "align", "reference_text": str(manual)},
    )

    assert res.status_code == 200
    entry = res.get_json()["file"]
    assert entry["mode"] == MODE_ALIGN
    assert entry["reference_text"] == str(manual)


def test_attaching_a_missing_text_file_is_refused(api, tmp_path):
    files = make_audio(tmp_path / "audio", "recording.mp3")
    api.client.post("/api/queue", json={"files": [str(f) for f in files]})

    res = api.client.post(
        "/api/queue/mode",
        json={
            "path": str(files[0]),
            "mode": "align",
            "reference_text": str(tmp_path / "ghost.txt"),
        },
    )

    assert res.status_code == 404


def test_reference_mode_endpoint(api, tmp_path):
    audio_dir = tmp_path / "audio"
    files = make_audio(audio_dir, "a.mp3")
    (audio_dir / "a.txt").write_text("words", encoding="utf-8")
    api.client.post("/api/queue", json={"files": [str(f) for f in files]})

    res = api.client.post("/api/queue/reference-mode", json={"enabled": True})
    body = res.get_json()

    assert res.status_code == 200
    assert body["matched"] == 1
    assert body["status"]["files"][0]["mode"] == MODE_ALIGN
