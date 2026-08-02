"""Transcripts mirror the folder structure they were scanned from."""

from __future__ import annotations

from pathlib import Path

from tertius.jobs import JobManager
from tertius.state import StateStore

from .fakes import fake_transcribe_file, make_audio, wait_until  # noqa: F401
from .fakes import FakeTranscriber


def test_subdir_is_recorded_relative_to_the_scanned_folder(tmp_path):
    root = tmp_path / "audio"
    top = make_audio(root, "intro.mp3")
    nested = make_audio(root / "Volume A", "V1_01.mp3")
    deeper = make_audio(root / "Volume A" / "part 2", "V1_02.mp3")

    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(top + nested + deeper, base_dir=root)

    assert store.get(top[0])["subdir"] == ""
    assert store.get(nested[0])["subdir"] == "Volume A"
    assert store.get(deeper[0])["subdir"] == "Volume A/part 2"


def test_no_base_dir_means_a_flat_output(tmp_path):
    """Uploads and individually chosen files keep the old behaviour."""
    files = make_audio(tmp_path / "audio" / "nested", "a.mp3")
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(files)
    assert store.get(files[0])["subdir"] == ""


def test_a_file_outside_the_scanned_folder_is_not_given_a_silly_path(tmp_path):
    """No `../../..` climbing out of the output directory."""
    outside = make_audio(tmp_path / "elsewhere", "stray.mp3")
    store = StateStore.for_output_dir(tmp_path / "out")
    store.add_files(outside, base_dir=tmp_path / "audio")
    assert store.get(outside[0])["subdir"] == ""


def test_transcripts_are_written_into_mirrored_folders(tmp_path):
    root = tmp_path / "audio"
    make_audio(root, "intro.mp3")
    make_audio(root / "Volume A", "talk.mp3")
    make_audio(root / "Volume B", "talk.mp3")  # same name, different folder
    out = tmp_path / "out"

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(out)
    everything = sorted(root.rglob("*.mp3"))
    manager.store.add_files(everything, base_dir=root)
    manager.start()
    manager.join(20)

    assert manager.status()["summary"]["done"] == 3
    assert (out / "intro.txt").is_file()
    assert (out / "Volume A" / "talk.txt").is_file()
    assert (out / "Volume B" / "talk.txt").is_file()

    # The collision this fixes: same stem, different folders, distinct content.
    a = (out / "Volume A" / "talk.txt").read_text(encoding="utf-8")
    b = (out / "Volume B" / "talk.txt").read_text(encoding="utf-8")
    assert a and b  # both written, neither overwrote the other


def test_recorded_outputs_point_at_the_mirrored_files(tmp_path):
    root = tmp_path / "audio"
    nested = make_audio(root / "Volume A", "talk.mp3")
    out = tmp_path / "out"

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(out)
    manager.store.add_files(nested, base_dir=root)
    manager.start()
    manager.join(20)

    outputs = manager.store.get(nested[0])["outputs"]
    assert outputs
    for written in outputs:
        assert Path(written).is_file()
        assert Path(written).parent == out / "Volume A"


def test_old_state_files_without_a_subdir_still_work(tmp_path):
    """Entries written before mirroring existed must not break."""
    files = make_audio(tmp_path / "audio", "a.mp3")
    out = tmp_path / "out"
    store = StateStore.for_output_dir(out)
    store.add_files(files)
    del store._data["files"][str(files[0].resolve())]["subdir"]  # pre-upgrade shape

    manager = JobManager(
        transcriber_factory=lambda options, on_download_progress=None: FakeTranscriber(
            options
        ),
        transcribe_fn=fake_transcribe_file,
    )
    manager.attach(out)
    manager.start()
    manager.join(20)

    assert (out / "a.txt").is_file()
    assert manager.status()["summary"]["done"] == 1
