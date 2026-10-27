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


def test_txt_is_one_sentence_per_line():
    """Whisper's segments are cut for timing, not for reading."""
    segments = [
        Segment(0, 1, "This is the first sentence. And here is"),
        Segment(1, 2, "the second one, split mid-thought."),
        Segment(2, 3, "A third."),
    ]

    assert segments_to_txt(segments) == (
        "This is the first sentence.\n"
        "And here is the second one, split mid-thought.\n"
        "A third.\n"
    )


def test_txt_keeps_an_abbreviation_off_a_line_break():
    segments = [Segment(0, 3, "Dr. Russell wrote it. Vol. 2 covers the rest.")]

    assert segments_to_txt(segments) == (
        "Dr. Russell wrote it.\nVol. 2 covers the rest.\n"
    )


def test_txt_changes_no_words():
    """Reflowing is a layout change; the transcript itself must be untouched."""
    segments = [
        Segment(0, 1, "one two. three"),
        Segment(1, 2, "four! five? six"),
    ]

    rendered = segments_to_txt(segments)

    assert rendered.replace("\n", " ").split() == "one two. three four! five? six".split()


def test_txt_of_unpunctuated_speech_stays_on_one_line():
    segments = [Segment(0, 1, "no punctuation here at all"), Segment(1, 2, "just words")]

    assert segments_to_txt(segments) == "no punctuation here at all just words\n"


def test_txt_of_silence_is_empty():
    assert segments_to_txt([]) == ""


def test_txt_of_only_blank_segments_is_empty():
    assert segments_to_txt([Segment(0, 1, "   "), Segment(1, 2, "")]) == ""


def test_srt_is_not_reflowed():
    """SRT lines are timing units and have to stay matched to their cues."""
    from tertius.transcribe import segments_to_srt

    segments = [Segment(0, 1, "First sentence. Second sentence.")]

    assert "First sentence. Second sentence." in segments_to_srt(segments)


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


class RecordingModel:
    """Captures what was actually asked of faster-whisper."""

    def __init__(self):
        self.kwargs = None

    def transcribe(self, audio, **kwargs):
        self.kwargs = kwargs
        return iter(()), object()


def _transcriber_with(options):
    from tertius.transcribe import WhisperTranscriber

    transcriber = WhisperTranscriber(options)
    model = RecordingModel()
    transcriber._model = model  # skip loading; we only care about the call
    return transcriber, model


def test_previous_text_conditioning_is_off_by_default():
    """A 38-minute talk lost every mark of punctuation from 14:45 onward.

    faster-whisper defaults `condition_on_previous_text` to True, prompting each
    30s window with the last one's text. One unpunctuated window becomes the
    prompt for the next, and the model never recovers - it kept the words right
    and emitted 2,197 one-word segments with no punctuation or capitals. The
    flag must reach the library, so this pins the call rather than the default.
    """
    options = TranscriptionOptions()
    assert options.condition_on_previous_text is False

    transcriber, model = _transcriber_with(options)
    transcriber.transcribe("talk.mp3")

    assert model.kwargs["condition_on_previous_text"] is False


def test_previous_text_conditioning_can_be_turned_back_on():
    transcriber, model = _transcriber_with(
        TranscriptionOptions(condition_on_previous_text=True)
    )
    transcriber.transcribe("talk.mp3")

    assert model.kwargs["condition_on_previous_text"] is True


class DetectingModel:
    """Records every call, and "detects" a fixed language when not given one."""

    def __init__(self, detects):
        self.detects = detects
        self.calls = []

    def transcribe(self, audio, **kwargs):
        from types import SimpleNamespace

        self.calls.append(kwargs)
        language = kwargs["language"] or self.detects
        return iter(()), SimpleNamespace(language=language, duration=1.0)


def _transcriber_detecting(options, detects):
    from tertius.transcribe import WhisperTranscriber

    transcriber = WhisperTranscriber(options)
    model = DetectingModel(detects)
    transcriber._model = model
    return transcriber, model


def test_chinese_is_shown_punctuation_in_every_window():
    """Unhinted, Whisper wrote 56 s of Chinese with no 。 or , at all.

    The hint goes in as `hotwords`, not `initial_prompt`: with previous-text
    conditioning off, faster-whisper drops the prompt after the first window,
    and punctuation stopped at 25 s. Hotwords are in every window's prompt.
    """
    from tertius.transcribe import PUNCTUATION_HINTS

    transcriber, model = _transcriber_detecting(
        TranscriptionOptions(language="zh"), detects="zh"
    )
    transcriber.transcribe("manna.wav")

    assert len(model.calls) == 1
    assert model.calls[0]["hotwords"] == PUNCTUATION_HINTS["zh"]
    assert "initial_prompt" not in model.calls[0]


def test_detected_chinese_is_asked_again_with_the_hint():
    """The hint has to be in the language, which auto-detect only knows after."""
    from tertius.transcribe import PUNCTUATION_HINTS

    transcriber, model = _transcriber_detecting(
        TranscriptionOptions(language=None), detects="zh"
    )
    result = transcriber.transcribe("manna.wav")

    assert [call["language"] for call in model.calls] == [None, "zh"]
    assert "hotwords" not in model.calls[0]
    assert model.calls[1]["hotwords"] == PUNCTUATION_HINTS["zh"]
    assert result.language == "zh"


@pytest.mark.parametrize("options_language", [None, "en"])
def test_other_languages_get_no_hint_and_one_pass(options_language):
    transcriber, model = _transcriber_detecting(
        TranscriptionOptions(language=options_language), detects="en"
    )
    transcriber.transcribe("talk.mp3")

    assert len(model.calls) == 1
    assert "hotwords" not in model.calls[0]


# Two segments read at a normal pace, about 2.5 words a second.
A = " ".join(["a"] * 25)
C = " ".join(["c"] * 15)


class SkippingModel:
    """Skips 10-14 s, as faster-whisper does at a window's end; decodes the
    gap when asked for it alone with `refill`."""

    def __init__(self, refill, language="he"):
        self.refill = refill
        self.language = language
        self.calls = []

    def transcribe(self, audio, **kwargs):
        from types import SimpleNamespace as S

        self.calls.append(kwargs)
        info = S(language=self.language, duration=20.0)
        if "clip_timestamps" in kwargs:
            return iter([S(start=a, end=b, text=t, words=None) for a, b, t in self.refill]), info
        return iter([S(start=0.0, end=10.0, text=A, words=None),
                     S(start=14.0, end=20.0, text=C, words=None)]), info


@pytest.fixture(autouse=True)
def _every_gap_has_speech(monkeypatch, request):
    """The fake models read no audio, so loudness is not measured; the test
    of the loudness check itself asks for the real one."""
    if "speech_loud" in request.node.name:
        return
    import tertius.transcribe as T

    monkeypatch.setattr(T, "_speech_loud", lambda path, gaps: gaps)


def _transcriber_skipping(refill, language="he"):
    from tertius.transcribe import WhisperTranscriber

    transcriber = WhisperTranscriber(TranscriptionOptions(language=language))
    transcriber._model = SkippingModel(refill, language)
    return transcriber


def test_speech_jumped_over_is_decoded_again_and_put_in_place():
    """0403 and 0510 lost a clause each this way, 26-30 s (2026-10-27)."""
    transcriber = _transcriber_skipping([(10.2, 13.6, "let every one of us")])
    result = transcriber.transcribe("reading.wav")

    assert [s.text for s in result.segments] == [A, "let every one of us", C]
    assert transcriber._model.calls[1]["clip_timestamps"] == [10.0, 14.0]


def test_a_thank_you_on_silence_is_not_put_in():
    """Whisper's text for a silent gap ran a full 30 s past it, every time."""
    transcriber = _transcriber_skipping([(10.0, 40.0, "תודה רבה.")])
    result = transcriber.transcribe("reading.wav")

    assert [s.text for s in result.segments] == [A, C]


def test_short_pauses_are_not_decoded_again():
    from tertius.transcribe import _gaps
    from types import SimpleNamespace as S

    segments = [S(start=0.0, end=5.0), S(start=6.0, end=9.0), S(start=11.0, end=15.0)]
    assert _gaps(segments, 15.5) == [(9.0, 11.0)]


@pytest.mark.parametrize("words", ["for.", "19. 19.", "תודה רבה."])
def test_a_word_or_two_in_a_gap_is_not_put_in(words):
    """What Whisper wrote in English and Hebrew gaps that held no speech."""
    transcriber = _transcriber_skipping([(10.2, 13.6, words)])
    result = transcriber.transcribe("reading.wav")

    assert [s.text for s in result.segments] == [A, C]


@pytest.mark.parametrize("language", ["zh", "fr"])
def test_only_measured_languages_are_decoded_again(language):
    """Chinese gaps came back invented; other languages are unmeasured."""
    transcriber = _transcriber_skipping([(10.2, 13.6, "let every one of us")], language)
    result = transcriber.transcribe("reading.wav")

    assert [s.text for s in result.segments] == [A, C]
    assert all("clip_timestamps" not in call for call in transcriber._model.calls)


class SwallowingModel:
    """`The text again` stretched over 30 s, the verse after it unwritten, as
    0421 came out (2026-10-27); decodes the verse when asked for after it."""

    def __init__(self):
        self.calls = []

    def transcribe(self, audio, **kwargs):
        from types import SimpleNamespace as S

        self.calls.append(kwargs)
        info = S(language="en", duration=84.0)
        clip = kwargs.get("clip_timestamps")
        if clip is None:
            return iter([S(start=0.0, end=60.0, text=" ".join(["w"] * 150), words=None),
                         S(start=60.2, end=90.2, text="The text again.", words=None)]), info
        if clip[0] > 61.0:
            return iter([S(start=61.5, end=70.0, text="We have not an high priest which cannot", words=None)]), info
        return iter([S(start=60.2, end=61.4, text="The text again.", words=None)]), info


def test_a_segment_that_swallows_speech_is_decoded_again():
    from tertius.transcribe import WhisperTranscriber

    transcriber = WhisperTranscriber(TranscriptionOptions(language="en"))
    transcriber._model = SwallowingModel()
    result = transcriber.transcribe("0421.mp3")

    assert [s.text for s in result.segments[-2:]] == [
        "The text again.", "We have not an high priest which cannot"
    ]
    assert result.segments[-2].end < 62.0


def test_a_normal_pace_is_not_decoded_again():
    from tertius.transcribe import _slow
    from types import SimpleNamespace as S

    segments = [S(start=0.0, end=9.0, text=" ".join(["w"] * 20)),   # 2.2 a second
                S(start=9.0, end=14.0, text="A short pause."),       # under 6 s
                S(start=14.0, end=29.0, text="It is like a plant.")]  # 0.3 a second
    assert [s.start for s in _slow(segments, 30.0)] == [14.0]


def test_the_old_text_decoded_again_is_not_put_in_twice():
    """0728: decoded after the old text's estimated end, the old text came back."""
    from tertius.transcribe import _repeats

    old = "It is only when we are hated because of our loyalty to truth"
    assert _repeats("It is only when we are hated because of our loyalty to truth,", old) > 0.9
    assert _repeats("If ye suffer for righteousness' sake, happy are ye.", old) < 0.6


class OpeningModel:
    """An opening segment of 15 s holding one sentence, the title and verse
    before it unwritten, as 0513 came out (2026-10-27)."""

    def transcribe(self, audio, **kwargs):
        from types import SimpleNamespace as S

        info = S(language="en", duration=40.0)
        clip = kwargs.get("clip_timestamps")
        comment = "Our Heavenly Father wishes us to be very attentive to His Word"
        if clip is None:
            return iter([S(start=0.3, end=15.4, text=comment, words=None),
                         S(start=15.4, end=40.0, text=" ".join(["w"] * 60), words=None)]), info
        if clip[0] < 1.0 and clip[1] < 12.0:
            return iter([S(start=0.3, end=9.0, text="Manna for May 13th. Behold, to obey is better than sacrifice", words=None)]), info
        return iter([S(start=0.3, end=15.0, text=comment, words=None)]), info


def test_what_an_opening_segment_swallowed_goes_before_it():
    from tertius.transcribe import WhisperTranscriber

    transcriber = WhisperTranscriber(TranscriptionOptions(language="en"))
    transcriber._model = OpeningModel()
    result = transcriber.transcribe("0513.mp3")

    assert [s.text for s in result.segments[:2]] == [
        "Manna for May 13th. Behold, to obey is better than sacrifice",
        "Our Heavenly Father wishes us to be very attentive to His Word",
    ]


@pytest.mark.parametrize(
    "start, end, dropped",
    [
        (60.0, 90.0, True),    # 0315's `Thank you.`, 0.9 s before a 60.9 s end
        (54.5, 61.6, False),   # 0719's last verse, 1.4 s over but begun 5.7 s before
        (59.5, 60.5, False),   # a last word that ends inside the audio
    ],
)
def test_text_on_the_closing_silence_is_dropped(start, end, dropped):
    from tertius.transcribe import _closing_filler
    from types import SimpleNamespace as S

    assert _closing_filler(S(start=start, end=end), 60.9) is dropped


def test_english_decoded_again_is_prompted_for_punctuation():
    """0520's opening came back `manna for may 20th a peculiar people...`."""
    from tertius.transcribe import REFILL_PROMPTS

    transcriber = _transcriber_skipping([(10.2, 13.6, "let every one of us")], "en")
    transcriber.transcribe("reading.wav")

    first, prompted, plain = transcriber._model.calls[:3]
    assert "initial_prompt" not in first
    assert prompted["initial_prompt"] == REFILL_PROMPTS["en"]
    # And without, in case the prompt loses speech (0317).
    assert "initial_prompt" not in plain and "clip_timestamps" in plain


def test_only_speech_loud_gaps_are_decoded_again_speech_loud(tmp_path):
    """0412's silent pause came back `Oh, my God.`; real skips were 46-70% loud."""
    import wave

    import numpy
    from tertius.transcribe import _speech_loud

    rate = 16_000
    rng = numpy.random.default_rng(0)
    speech = 0.2 * rng.standard_normal(rate * 10)
    quiet = 0.002 * rng.standard_normal(rate * 2)
    audio = numpy.concatenate([speech, quiet, speech])  # 0-10 s, 10-12 s, 12-22 s
    path = tmp_path / "reading.wav"
    with wave.open(str(path), "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes((numpy.clip(audio, -1, 1) * 32767).astype("<i2").tobytes())

    assert _speech_loud(path, [(10.0, 12.0), (14.0, 16.0)]) == [(14.0, 16.0)]
