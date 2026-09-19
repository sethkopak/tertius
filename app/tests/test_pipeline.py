"""Transcribe → translate → speak, as three stages of one job.

The feature these cover exists because of a real failure: speaking used to be a
*source kind* rather than a stage, so a queue could be translated or spoken but
never both. Asked for Spanish audio from an English talk - the whole point -
the app could only offer a speech-language menu that does not translate, and a
run produced English audio for someone who had picked Chinese, reporting
success.

Nothing here loads a model. The fakes stand in for all three.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tertius.config import TranscriptionOptions
from tertius.speech import best_voice_window, read_text_source
from tertius.state import MODE_TEXT
from tertius.transcribe import Segment, TranscriptionResult

from .fakes import FakeSpeaker, FakeTranslator, make_audio


# --------------------------------------------------------- the derived language


def test_translating_makes_the_target_the_speaking_language():
    """The menu that caused the bug does not get a say when translating."""
    options = TranscriptionOptions(
        translate=True, target_language="es", speak=True, speech_language="zh"
    )
    # `zh` is stale UI state; the words about to be spoken are Spanish.
    assert options.resolved_speech_language() == "es"


def test_without_a_translation_the_detected_language_wins():
    options = TranscriptionOptions(speak=True)
    assert options.resolved_speech_language("fr") == "fr"


def test_a_text_source_may_still_state_its_own_language():
    options = TranscriptionOptions(speak=True, speech_language="de")
    assert options.resolved_speech_language() == "de"


def test_a_target_the_voice_model_cannot_say_is_refused_up_front():
    """Translating a whole queue into Romanian then failing to say it."""
    with pytest.raises(ValueError, match="cannot speak"):
        TranscriptionOptions(translate=True, target_language="ro", speak=True)

    # Fine when nothing is going to read it aloud.
    assert TranscriptionOptions(translate=True, target_language="ro").target_language == "ro"


# ------------------------------------------------------------- the voice window


def test_the_voice_window_skips_a_sparse_opening():
    """Chatterbox conditions on ~10s; handed a talk that is the talk's first 10s.

    Measured on a real devotional file: 49% of its first ten seconds was
    near-silence, and that was the half the model was cloning from.
    """
    segments = [
        Segment(0.0, 0.8, "title"),      # a lone announcement, then a long gap
        Segment(30.0, 38.0, "speech"),
        Segment(38.0, 46.0, "more speech"),
    ]
    start, duration = best_voice_window(segments, wanted=10.0)
    assert (start, duration) == (30.0, 10.0)


def test_the_voice_window_falls_back_when_there_are_no_timings():
    assert best_voice_window([], wanted=10.0) == (0.0, 10.0)
    assert best_voice_window(None, wanted=10.0) == (0.0, 10.0)


# ------------------------------------------------- audio → translate → speak


def _real_wav(path, seconds=40.0, rate=8000):
    """A decodable file, so the voice sampler has something real to cut.

    `make_audio` writes placeholder bytes, which is right for everything that
    only ever hands a path to a mocked model - but the voice sampler actually
    opens the file.
    """
    import math
    import wave
    from array import array

    path.parent.mkdir(parents=True, exist_ok=True)
    frames = array(
        "h",
        (int(8000 * math.sin(i * 0.05)) for i in range(int(seconds * rate))),
    )
    with wave.open(str(path), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(rate)
        handle.writeframes(frames.tobytes())
    return path


def _queue_audio(api, tmp_path, name="talk.mp3"):
    (audio,) = make_audio(tmp_path / "audio", name)
    api.manager.attach(api.output_dir)
    api.manager.store.add_files([audio])
    return audio


def test_a_talk_is_transcribed_translated_and_read_aloud(api, tmp_path):
    """The workflow the whole change exists for."""
    audio = _queue_audio(api, tmp_path)

    api.manager.start(
        output_dir=api.output_dir,
        options={
            "translate": True,
            "target_language": "es",
            "speak": True,
            "formats": ["txt", "srt"],
        },
    )
    api.wait_done()

    entry = api.manager.store.get(audio)
    assert entry["status"] == "done", entry.get("error")
    names = sorted(Path(p).name for p in entry["outputs"])
    # The transcript, the translation, and the audio of the translation.
    assert "talk.txt" in names            # the transcript
    assert "talk.es.txt" in names         # the translation
    assert "talk.es.srt" in names         # translated cues, timed to the original
    assert "talk.es.spoken.wav" in names  # the reading
    # The reading's own cues never overwrite the translation's: one is timed
    # against the original recording, the other against generated audio.
    assert "talk.es.spoken.srt" in names


def test_the_reading_is_in_the_target_language_not_the_menu(api, tmp_path):
    audio = _queue_audio(api, tmp_path)

    api.manager.start(
        output_dir=api.output_dir,
        options={
            "translate": True,
            "target_language": "es",
            "speak": True,
            # Stale, and must not reach the model.
            "speech_language": "zh",
            "formats": ["txt"],
        },
    )
    api.wait_done()

    assert api.speaker is not None and api.speaker.calls
    languages = {language for _t, _s, language, _v in api.speaker.calls}
    assert languages == {"es"}


def test_the_reading_uses_the_sentence_translation_not_the_fragments(api, tmp_path):
    """Segment translations are the measurably worse ones.

    A mistake in a file can be skimmed past. The same mistake read out loud
    cannot, so speaking takes the sentence stream.
    """
    audio = _queue_audio(api, tmp_path)

    api.manager.start(
        output_dir=api.output_dir,
        options={
            "translate": True,
            "target_language": "es",
            "speak": True,
            "formats": ["srt"],  # no .txt asked for at all
        },
    )
    api.wait_done()

    # The sentence pass ran even though no `.txt` was wanted, because the
    # reading needs it.
    assert api.translator is not None
    assert len(api.translator.batches) >= 2, api.translator.batches
    spoken = " ".join(text for text, _s, _l, _v in api.speaker.calls)
    assert "[es]" in spoken  # the fake marks what it translated


def test_the_voice_is_sampled_from_the_recording(api, tmp_path):
    """No clip chosen, so the speaker in the recording is the voice."""
    audio = _real_wav(tmp_path / "audio" / "talk.wav")
    api.manager.attach(api.output_dir)
    api.manager.store.add_files([audio])

    api.manager.start(
        output_dir=api.output_dir,
        options={"translate": True, "target_language": "es", "speak": True},
    )
    api.wait_done()

    voices = {voice for _t, _s, _l, voice in api.speaker.calls}
    assert len(voices) == 1
    (voice,) = voices
    # A clip cut from this recording, not the model's default and not a path
    # the user had to supply.
    assert voice is not None
    assert Path(voice).name.startswith("talk")


def test_an_explicit_clip_still_wins(api, tmp_path):
    audio = _queue_audio(api, tmp_path)
    clip = tmp_path / "myvoice.wav"
    clip.write_bytes(b"\x00")

    api.manager.start(
        output_dir=api.output_dir,
        options={
            "translate": True,
            "target_language": "es",
            "speak": True,
            "speech_voice": str(clip),
        },
    )
    api.wait_done()

    voices = {voice for _t, _s, _l, voice in api.speaker.calls}
    assert voices == {str(clip)}


def test_a_failed_reading_does_not_throw_away_the_transcript(api, tmp_path):
    """The transcript is already written and correct by then.

    Marking the file failed would send a resume back to redo an hour of
    transcription over a voice model that would not load.
    """
    audio = _queue_audio(api, tmp_path)
    api.speaker_fails = True

    api.manager.start(
        output_dir=api.output_dir,
        options={
            "translate": True,
            "target_language": "es",
            "speak": True,
            "formats": ["txt"],
        },
    )
    api.wait_done()

    entry = api.manager.store.get(audio)
    assert entry["status"] == "done"
    names = sorted(Path(p).name for p in entry["outputs"])
    assert "talk.txt" in names and "talk.es.txt" in names
    assert not any(n.endswith(".wav") for n in names)
    status = api.manager.status(include_files=False)
    assert "could not be read aloud" in (status["notice"] or "")


def test_no_speaker_is_loaded_when_the_stage_is_off(api, tmp_path):
    _queue_audio(api, tmp_path)

    api.manager.start(
        output_dir=api.output_dir,
        options={"translate": True, "target_language": "es", "speak": False},
    )
    api.wait_done()

    assert api.speaker is None


# --------------------------------------------------- text → translate → speak


def test_style_tags_survive_being_translated(tmp_path):
    """Parse first, then translate, or the tag goes to the model as a word.

    Translating the file and parsing afterwards cannot work: `[solemn]` would
    have been rendered into the target language, or dropped.
    """
    source = tmp_path / "script.txt"
    source.write_text(
        "[solemn] In the beginning.\n\n[bright] And there was light.",
        encoding="utf-8",
    )
    speaker = FakeSpeaker()
    translator = FakeTranslator()

    written, result = read_text_source(
        source,
        tmp_path / "out",
        speaker,
        translator=translator,
        target_language="es",
        formats=("txt", "json"),
    )

    styles = [style for _t, style, _l, _v in speaker.calls]
    assert styles == ["solemn", "bright"]
    # The tag itself never reached the translator.
    assert all("[solemn]" not in text for batch in translator.batches for text in batch)
    # And what was spoken is the translated text.
    assert all("[es]" in text for text, _s, _l, _v in speaker.calls)

    names = sorted(Path(p).name for p in written)
    assert names == [
        "script.es.spoken.json",
        "script.es.spoken.wav",
        "script.es.txt",
    ]


def test_a_text_file_can_be_read_without_translating(tmp_path):
    source = tmp_path / "script.txt"
    source.write_text("Plain words.", encoding="utf-8")
    speaker = FakeSpeaker()

    written, _result = read_text_source(
        source, tmp_path / "out", speaker, language="en", formats=("srt",)
    )

    names = sorted(Path(p).name for p in written)
    assert names == ["script.en.spoken.srt", "script.en.spoken.wav"]
    assert speaker.calls[0][2] == "en"


def test_a_text_file_with_neither_stage_on_says_so(api, tmp_path):
    source = tmp_path / "notes.txt"
    source.write_text("Some text.", encoding="utf-8")
    api.manager.attach(api.output_dir)
    api.manager.store.add_files([source])

    api.manager.start(
        output_dir=api.output_dir, options={"translate": False, "speak": False}
    )
    api.wait_done()

    entry = api.manager.store.get(source)
    assert entry["status"] == "failed"
    assert "neither Translate nor Read aloud" in entry["error"]
    assert api.manager.store.get(source)["mode"] == MODE_TEXT


# ------------------------------------------------------------------- the API


def test_the_target_menu_narrows_to_what_can_be_spoken(api, monkeypatch):
    """Offering a language the last stage cannot say is the same bug again."""
    import tertius.app as app_module

    monkeypatch.setattr(
        app_module, "is_media_file", app_module.is_media_file, raising=False
    )
    from tertius import translate as translate_module

    monkeypatch.setattr(translate_module, "is_converted", lambda name: True)
    monkeypatch.setattr(
        translate_module,
        "supported_target_languages",
        lambda name: ("en", "es", "ro", "cy", "zh"),
    )

    wide = api.client.get("/api/translation/languages?model=m2m100-418M").get_json()
    assert "ro" in wide["languages"]
    assert wide["restricted_to_speakable"] is False

    narrow = api.client.get(
        "/api/translation/languages?model=m2m100-418M&speak=1"
        "&speech_model=chatterbox-multilingual"
    ).get_json()
    assert narrow["restricted_to_speakable"] is True
    # Romanian and Welsh are translatable and unspeakable.
    assert "ro" not in narrow["languages"]
    assert "cy" not in narrow["languages"]
    assert set(narrow["languages"]) == {"en", "es", "zh"}


def test_the_page_reads_as_a_pipeline(api):
    page = api.client.get("/").get_data(as_text=True)
    for marker in (
        ">Transcribe<",
        ">Translate<",
        ">Read aloud<",
        "speak-row",
        'data-source="media"',
        "pipeline-hint",
    ):
        assert marker in page, marker
