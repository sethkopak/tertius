"""Finding text files that don't live next to the audio.

Reported: an uploaded V1_01.mp3 could not find V1_01.txt even though they sat
in the same folder on disk - because the upload is copied into _uploads/ and
the browser never sends the original location.
"""

from __future__ import annotations

from pathlib import Path

from tertius.state import MODE_ALIGN, MODE_UNDECIDED, StateStore

from .fakes import make_audio


def test_text_beside_the_audio_is_still_found_first(tmp_path):
    audio_dir = tmp_path / "audio"
    (audio,) = make_audio(audio_dir, "V1_01.mp3")
    (audio_dir / "V1_01.txt").write_text("beside", encoding="utf-8")
    elsewhere = tmp_path / "texts"
    elsewhere.mkdir()
    (elsewhere / "V1_01.txt").write_text("elsewhere", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.set_reference_dir(elsewhere)
    store.add_files([audio], match_reference_text=True)

    found = Path(store.get(audio)["reference_text"])
    assert found.read_text(encoding="utf-8") == "beside"


def test_text_folder_covers_uploaded_audio(tmp_path):
    """The actual reported case: audio in _uploads, text in a real folder."""
    uploads = tmp_path / "out" / "_uploads"
    (audio,) = make_audio(uploads, "V1_01.mp3")
    texts = tmp_path / "my texts"
    texts.mkdir()
    (texts / "V1_01.txt").write_text("the words", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)
    assert store.get(audio)["mode"] == MODE_UNDECIDED  # nothing beside it

    store.set_reference_dir(texts)
    matched, undecided, _ = store.apply_reference_mode(True)

    assert (matched, undecided) == (1, 0)
    assert store.get(audio)["mode"] == MODE_ALIGN
    assert Path(store.get(audio)["reference_text"]).parent == texts


def test_text_folder_is_searched_recursively(tmp_path):
    """People keep their texts in a tree, not one flat folder."""
    (audio,) = make_audio(tmp_path / "audio", "V1_01.mp3")
    nested = tmp_path / "texts" / "Volume A" / "part 2"
    nested.mkdir(parents=True)
    (nested / "V1_01.txt").write_text("deep", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.set_reference_dir(tmp_path / "texts")
    store.add_files([audio], match_reference_text=True)

    assert store.get(audio)["mode"] == MODE_ALIGN
    assert Path(store.get(audio)["reference_text"]).parent == nested


def test_a_near_miss_in_the_text_folder_is_still_not_matched(tmp_path):
    (audio,) = make_audio(tmp_path / "audio", "V1_01.mp3")
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "V1_02.txt").write_text("wrong one", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.set_reference_dir(texts)
    store.add_files([audio], match_reference_text=True)

    assert store.get(audio)["mode"] == MODE_UNDECIDED


def test_search_locations_are_reported(tmp_path):
    """So the UI can say where it looked instead of just "not found"."""
    (audio,) = make_audio(tmp_path / "audio", "V1_01.mp3")
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files([audio], match_reference_text=True)

    entry = next(f for f in store.snapshot()["files"] if f["name"] == "V1_01.mp3")
    assert entry["searched"] == [str((tmp_path / "audio").resolve())]

    store.set_reference_dir(tmp_path / "texts2")
    (tmp_path / "texts2").mkdir()
    entry = next(f for f in store.snapshot()["files"] if f["name"] == "V1_01.mp3")
    assert len(entry["searched"]) == 2


def test_reference_dir_survives_a_reload(tmp_path):
    out = tmp_path / "out"
    texts = tmp_path / "texts"
    texts.mkdir()
    store = StateStore.for_output_dir(out)
    store.set_reference_dir(texts)

    reloaded = StateStore.for_output_dir(out)
    assert reloaded.reference_dir == str(texts.resolve())


def test_clearing_the_text_folder(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")
    store.set_reference_dir(tmp_path)
    store.set_reference_dir(None)
    assert store.reference_dir is None


def test_endpoint_sets_the_folder_and_rematches(tmp_path):
    from .conftest import ApiHarness

    api = ApiHarness(tmp_path)
    uploads = tmp_path / "out" / "_uploads"
    (audio,) = make_audio(uploads, "V1_01.mp3")
    texts = tmp_path / "texts"
    texts.mkdir()
    (texts / "V1_01.txt").write_text("the words", encoding="utf-8")
    api.client.post("/api/queue", json={"files": [str(audio)]})

    res = api.client.post(
        "/api/queue/reference-mode",
        json={"enabled": True, "reference_dir": str(texts)},
    )
    body = res.get_json()

    assert body["matched"] == 1
    assert body["reference_dir"] == str(texts.resolve())
    assert body["status"]["files"][0]["mode"] == MODE_ALIGN


def test_endpoint_rejects_a_folder_that_does_not_exist(tmp_path):
    from .conftest import ApiHarness

    api = ApiHarness(tmp_path)
    res = api.client.post(
        "/api/queue/reference-mode",
        json={"enabled": True, "reference_dir": str(tmp_path / "nope")},
    )
    assert res.status_code == 404
