"""`.json` output: the transcript as data.

Two renderers, because there are two kinds of run. A fresh transcription writes
Whisper's segments; timestamping supplied text writes your chunks, including
the ones that were never spoken and so carry no time.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from tertius.alignment import AlignmentResult, Chunk, render_json
from tertius.config import (
    ALIGNMENT_SHAPE,
    JSON_SHAPE_VERSION,
    OUTPUT_FORMATS,
    TRANSCRIPTION_SHAPE,
    TranscriptionOptions,
)
from tertius.transcribe import (
    Segment,
    TranscriptionResult,
    result_to_json,
    safe_output_path,
    write_outputs,
)


def test_json_is_an_offerable_format():
    assert "json" in OUTPUT_FORMATS
    assert TranscriptionOptions(formats=["json"]).formats == ["json"]


# ------------------------------------------------------------- shape data
#
# The shape used to say nothing about itself: a reader could not tell which of
# the two payloads it held, nor that either might change under it.

def test_a_transcription_declares_its_shape():
    payload = json.loads(result_to_json(sample_result(), Path("a.wav")))

    assert payload["version"] == JSON_SHAPE_VERSION
    assert payload["kind"] == TRANSCRIPTION_SHAPE


def test_an_alignment_declares_its_shape():
    payload = json.loads(render_json(AlignmentResult(chunks=[], granularity="sentence")))

    assert payload["version"] == JSON_SHAPE_VERSION
    assert payload["kind"] == ALIGNMENT_SHAPE


def test_the_two_shapes_are_told_apart_by_kind_alone():
    """Both land as `.json` beside the audio; the extension cannot say which."""
    transcription = json.loads(result_to_json(sample_result(), Path("a.wav")))
    alignment = json.loads(render_json(AlignmentResult(chunks=[], granularity="auto")))

    assert transcription["kind"] != alignment["kind"]
    assert "segments" in transcription and "chunks" not in transcription
    assert "chunks" in alignment and "segments" not in alignment


def test_both_renderers_stamp_the_same_version():
    """One constant, two writers - the drift this key exists to catch."""
    transcription = json.loads(result_to_json(sample_result(), Path("a.wav")))
    alignment = json.loads(render_json(AlignmentResult(chunks=[], granularity="auto")))

    assert transcription["version"] == alignment["version"]


def assert_shape_keys_lead(rendered: str) -> None:
    """Line 0 is the opening brace; the two shape keys follow it."""
    lines = rendered.splitlines()

    assert '"version"' in lines[1]
    assert '"kind"' in lines[2]


def test_a_transcription_meets_the_reader_with_its_shape_keys():
    assert_shape_keys_lead(result_to_json(sample_result(), Path("a.wav")))


def test_an_alignment_meets_the_reader_with_its_shape_keys():
    assert_shape_keys_lead(render_json(AlignmentResult(chunks=[], granularity="auto")))


# ------------------------------------------------------------- transcription

def sample_result() -> TranscriptionResult:
    return TranscriptionResult(
        segments=[
            Segment(0.0, 2.8199999, "The first line."),
            Segment(3.84, 6.92, "The second line."),
            Segment(7.0, 7.5, "   "),
        ],
        language="en",
        duration=12.5,
    )


def test_json_carries_every_segment_with_its_times():
    payload = json.loads(result_to_json(sample_result(), Path("reading.wav")))

    assert payload["source"] == "reading.wav"
    assert payload["language"] == "en"
    assert payload["duration"] == 12.5
    assert payload["segments"] == [
        {"id": 0, "start": 0.0, "end": 2.82, "text": "The first line."},
        {"id": 1, "start": 3.84, "end": 6.92, "text": "The second line."},
    ]


def test_json_drops_blank_segments():
    payload = json.loads(result_to_json(sample_result(), Path("a.wav")))

    assert all(s["text"].strip() for s in payload["segments"])


def test_json_reports_an_unknown_language_as_null_rather_than_guessing():
    result = TranscriptionResult(segments=[Segment(0, 1, "hi")])

    payload = json.loads(result_to_json(result, Path("a.wav")))

    assert payload["language"] is None
    assert payload["duration"] is None


def test_json_keeps_non_ascii_readable():
    """ensure_ascii would turn every accent into an escape."""
    result = TranscriptionResult(segments=[Segment(0, 1, "café Ελλάδα")], language="el")

    rendered = result_to_json(result, Path("a.wav"))

    assert "café Ελλάδα" in rendered


def test_json_is_written_alongside_the_other_formats(tmp_path):
    written = write_outputs(
        Path("talk.mp3"), sample_result(), tmp_path, ["txt", "srt", "json"]
    )

    assert [Path(p).name for p in written] == ["talk.txt", "talk.srt", "talk.json"]
    assert json.loads((tmp_path / "talk.json").read_text(encoding="utf-8"))


def test_json_survives_a_round_trip_through_the_file(tmp_path):
    write_outputs(Path("talk.mp3"), sample_result(), tmp_path, ["json"])

    payload = json.loads((tmp_path / "talk.json").read_text(encoding="utf-8"))

    assert payload["segments"][0]["text"] == "The first line."


# ----------------------------------------------------------------- alignment

def test_alignment_json_keeps_untimed_chunks():
    """The .srt cannot carry these; dropping them here would misrepresent it."""
    result = AlignmentResult(
        chunks=[
            Chunk(text="A title page", words=["a", "title", "page"]),
            Chunk(text="Spoken words.", words=["spoken", "words"], start=1.0, end=2.0),
        ],
        granularity="sentence",
    )

    payload = json.loads(render_json(result))

    assert [c["timed"] for c in payload["chunks"]] == [False, True]
    assert payload["chunks"][0]["start"] is None
    assert payload["chunks"][0]["text"] == "A title page"
    assert payload["summary"]["unmatched"] == 1


def test_alignment_json_reports_the_granularity_used():
    payload = json.loads(render_json(AlignmentResult(chunks=[], granularity="paragraph")))

    assert payload["granularity"] == "paragraph"


# ------------------------------------------------- not over Tertius's own files

@pytest.mark.parametrize("stem", ["transcription_state", "tertius"])
def test_a_transcript_never_overwrites_tertius_own_files(tmp_path, stem):
    """`transcription_state.mp3` must not write over the queue's state file."""
    fmt = "json" if stem == "transcription_state" else "log"
    target = safe_output_path(tmp_path, stem, fmt)

    assert target.name == f"{stem}.transcript.{fmt}"


def test_an_ordinary_name_is_left_alone(tmp_path):
    assert safe_output_path(tmp_path, "talk", "json").name == "talk.json"


def test_the_state_file_survives_transcribing_a_file_named_after_it(tmp_path):
    state = tmp_path / "transcription_state.json"
    state.write_text('{"files": {}}', encoding="utf-8")

    write_outputs(Path("transcription_state.mp3"), sample_result(), tmp_path, ["json"])

    assert json.loads(state.read_text(encoding="utf-8")) == {"files": {}}
    assert (tmp_path / "transcription_state.transcript.json").is_file()


# ------------------------------------------------------------------- BOM

def test_supplied_text_with_a_bom_does_not_carry_it_into_the_output(tmp_path):
    """Notepad and PowerShell both write one; read as plain utf-8 it survives
    as an invisible character glued to the first word, which then shows up in
    the transcript and stops that chunk matching the audio."""
    from tertius.alignment import chunk_text

    path = tmp_path / "supplied.txt"
    path.write_bytes("﻿A Title Page\n\nSpoken words.".encode("utf-8"))

    text = path.read_text(encoding="utf-8-sig", errors="replace")
    chunks, _ = chunk_text(text, "paragraph")

    assert chunks[0].text == "A Title Page"
    assert not chunks[0].text.startswith("﻿")


# ------------------------------------------------------- a new format stays off

def test_a_new_format_does_not_switch_itself_on(api):
    """The page seeded its format set from every chip on the row, so adding one
    would have started writing it for everyone with no saved settings."""
    page = api.client.get("/").get_data(as_text=True)

    assert 'data-format="txt"' in page and 'data-format="json"' in page
    json_chip = page[page.index('data-format="json"'):][:200]
    assert 'aria-pressed="false"' in json_chip

    txt_chip = page[page.index('data-format="txt"'):][:200]
    assert 'aria-pressed="true"' in txt_chip


def test_the_default_formats_are_still_txt_and_srt():
    assert TranscriptionOptions().formats == ["txt", "srt"]
