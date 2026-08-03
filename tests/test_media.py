"""Media lengths: nice to have, never load-bearing.

A file whose header will not parse must still queue and still transcribe, so
every probe failure here has to be silent and leave the duration unknown.
"""

from __future__ import annotations

from tertius.media import fill_missing_durations, probe_duration
from tertius.state import StateStore

from .fakes import make_audio


def test_probe_returns_none_for_a_file_that_is_not_media(tmp_path):
    junk = tmp_path / "not-audio.mp3"
    junk.write_bytes(b"\x00 definitely not an mp3")
    assert probe_duration(junk) is None


def test_probe_returns_none_for_a_missing_file(tmp_path):
    assert probe_duration(tmp_path / "gone.wav") is None


def test_unreadable_files_leave_the_duration_unknown(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")
    files = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    store.add_files(files)

    assert fill_missing_durations(store) == 0
    assert all(f["duration"] is None for f in store.snapshot()["files"])


def test_set_durations_writes_only_the_missing_ones(tmp_path):
    store = StateStore.for_output_dir(tmp_path / "out")
    first, second = make_audio(tmp_path / "audio", "a.mp3", "b.mp3")
    store.add_files([first, second])
    store.set_durations({str(first): 12.5})

    # A second probe must not overwrite a length already recorded, and a file
    # that has since been removed must not resurrect itself.
    store.remove_file(second)
    written = store.set_durations({str(first): 99.0, str(second): 30.0})

    assert written == 0
    assert store.get(first)["duration"] == 12.5
    assert store.get(second) is None
