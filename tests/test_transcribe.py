"""Output rendering and writing (no model involved)."""

from __future__ import annotations

import pytest
from tertius.config import TranscriptionOptions
from tertius.transcribe import (
    Segment,
    TranscriptionResult,
    format_timestamp,
    segments_to_srt,
    segments_to_txt,
    write_outputs,
)

from .fakes import make_audio


@pytest.mark.parametrize(
    "seconds,expected",
    [
        (0, "00:00:00,000"),
        (1.5, "00:00:01,500"),
        (61.25, "00:01:01,250"),
        (3661.007, "01:01:01,007"),
        (-3, "00:00:00,000"),
    ],
)
def test_format_timestamp(seconds, expected):
    assert format_timestamp(seconds) == expected


def test_txt_is_one_line_per_segment_trimmed():
    segments = [Segment(0, 1, " hello "), Segment(1, 2, "world"), Segment(2, 3, "  ")]
    assert segments_to_txt(segments) == "hello\nworld\n"


def test_txt_of_silence_is_empty():
    assert segments_to_txt([]) == ""


def test_srt_numbers_only_non_empty_segments():
    segments = [Segment(0, 1.5, "one"), Segment(1.5, 2, "   "), Segment(2, 3, "two")]
    srt = segments_to_srt(segments)
    assert srt == (
        "1\n00:00:00,000 --> 00:00:01,500\none\n"
        "\n"
        "2\n00:00:02,000 --> 00:00:03,000\ntwo\n"
    )


def test_write_outputs_names_files_after_the_source(tmp_path):
    (source,) = make_audio(tmp_path / "audio", "lecture1.mp3")
    result = TranscriptionResult(segments=[Segment(0, 1, "hi")], language="en")
    out = tmp_path / "out"

    written = write_outputs(source, result, out, ["txt", "srt"])

    assert [p.name for p in sorted(out.iterdir())] == ["lecture1.srt", "lecture1.txt"]
    assert set(written) == {str(out / "lecture1.txt"), str(out / "lecture1.srt")}
    assert (out / "lecture1.txt").read_text(encoding="utf-8") == "hi\n"


def test_write_outputs_leaves_no_partial_files(tmp_path):
    (source,) = make_audio(tmp_path / "audio", "a.mp3")
    out = tmp_path / "out"
    write_outputs(source, TranscriptionResult([Segment(0, 1, "x")]), out, ["txt"])
    assert [p.name for p in out.iterdir()] == ["a.txt"]


def test_rerun_overwrites_rather_than_appends(tmp_path):
    (source,) = make_audio(tmp_path / "audio", "a.mp3")
    out = tmp_path / "out"
    write_outputs(source, TranscriptionResult([Segment(0, 1, "first")]), out, ["txt"])
    write_outputs(source, TranscriptionResult([Segment(0, 1, "second")]), out, ["txt"])
    assert (out / "a.txt").read_text(encoding="utf-8") == "second\n"


def test_language_codes_are_validated_up_front(monkeypatch):
    """A typo must fail the job, not fail every file in it one at a time."""
    from tertius import config

    monkeypatch.setattr(
        config, "known_language_codes", lambda: frozenset({"en", "es", "fr"})
    )

    assert TranscriptionOptions(language="es").language == "es"
    assert TranscriptionOptions(language=" FR ").language == "fr"  # normalised

    with pytest.raises(ValueError, match="not a Whisper language code"):
        TranscriptionOptions(language="spanish")


def test_language_check_is_skipped_without_faster_whisper(monkeypatch):
    from tertius import config

    monkeypatch.setattr(config, "known_language_codes", lambda: None)
    assert TranscriptionOptions(language="xx").language == "xx"


def test_real_language_codes_cover_the_usual_suspects():
    from tertius.config import known_language_codes

    codes = known_language_codes()
    if codes is None:
        pytest.skip("faster-whisper not installed")
    assert len(codes) > 90
    for code in ("en", "es", "fr", "de", "zh", "ja", "ko", "ar", "hi", "pt"):
        assert code in codes


def test_options_validation():
    assert TranscriptionOptions(language="  ").language is None
    assert TranscriptionOptions().resolved_compute_type() is None
    assert TranscriptionOptions(compute_type="int8").resolved_compute_type() == "int8"

    with pytest.raises(ValueError, match="model size"):
        TranscriptionOptions(model_size="huge")
    with pytest.raises(ValueError, match="device"):
        TranscriptionOptions(device="tpu")
    with pytest.raises(ValueError, match="output format"):
        TranscriptionOptions(formats=["vtt"])
    with pytest.raises(ValueError, match="at least one output format"):
        TranscriptionOptions(formats=[])


def test_default_model_is_turbo():
    assert TranscriptionOptions().model_size == "large-v3-turbo"


def test_dropped_aliases_still_resolve_rather_than_erroring():
    """`turbo` is no longer offered, but an old state file may still name it."""
    assert TranscriptionOptions(model_size="turbo").model_size == "large-v3-turbo"
    assert TranscriptionOptions(model_size="large").model_size == "large-v3"
    with pytest.raises(ValueError, match="unknown model size"):
        TranscriptionOptions(model_size="turbocharged")


def test_offered_model_names_are_ones_faster_whisper_accepts():
    """Guards against offering a model name the library would reject.

    Skipped where faster-whisper is not installed; the rest of the suite never
    needs it.
    """
    utils = pytest.importorskip("faster_whisper.utils")
    from tertius.config import MODEL_SIZES

    unknown = [m for m in MODEL_SIZES if m not in utils._MODELS]
    assert unknown == []


def test_options_round_trip():
    options = TranscriptionOptions(model_size="base", language="fr", formats=["srt"])
    restored = TranscriptionOptions.from_dict(options.to_dict())
    assert restored == options
    # Unknown keys from an older state file are ignored, not fatal.
    assert TranscriptionOptions.from_dict({"model_size": "tiny", "legacy": 1}).model_size == "tiny"
