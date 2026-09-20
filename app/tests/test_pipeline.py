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


def test_what_whisper_detected_beats_a_stale_menu():
    """Reported: Russian audio transcribed to Russian, then read as English.

    The menu had been left on `en` from an earlier run and outranked a language
    the app had just identified from the audio itself.
    """
    options = TranscriptionOptions(speak=True, speech_language="en")
    assert options.resolved_speech_language("ru") == "ru"


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


# --------------------------------------------------------- scripts without capitals


ZH = '每日天堂曼娜。每日天堂曼娜。祝福我們的上帝，讓他的讚美被聽到。'


def test_chinese_splits_into_sentences():
    """The splitter wanted an ASCII terminator, a space, and a capital.

    Chinese has none of the three: an ideographic full stop, usually no space,
    and no case at all - so a whole translation came back as one "sentence".
    Invisible in a `.txt`, fatal when something reads it aloud.
    """
    from tertius.alignment import split_sentences

    assert len(split_sentences(ZH)) == 3


def test_every_script_tertius_can_speak_splits_into_sentences():
    """Three assumptions about English, and scripts break them differently.

    Chinese fails all three - ideographic stop, no space, no capital. Russian
    and Greek fail only the *third*: an ordinary full stop and a space, then a
    capital that `[A-Z]` does not match because `re` classes like that stay
    ASCII. That is why Cyrillic survived the first attempt at this fix, and it
    cost 552 seconds of GPU on one 70-second Russian file read as a single
    chunk.
    """
    from tertius.alignment import split_sentences

    three_sentences = {
        "en": "Bless our God. Let his praise be heard. This keeps us alive.",
        "ru": "Благослови Бога. Пусть его хвала будет услышана. Это оживляет душу.",
        "el": "Ευλογείτε τον Θεό. Ας ακουστεί ο έπαινός. Αυτό κρατά ζωντανή.",
        "zh": "每日天堂曼娜。祝福上帝。讓他的讚美被聽到。",
    }
    for code, text in three_sentences.items():
        assert len(split_sentences(text)) == 3, (code, split_sentences(text))


def test_abbreviations_are_still_protected():
    """The Unicode-aware check must not undo the older fix.

    `endswith` on an abbreviation list once glued the next sentence onto any
    word ending in one - and "Christ." ends with "st." constantly in scripture.
    """
    from tertius.alignment import split_sentences

    assert len(split_sentences("He met Dr. Smith. They spoke of Christ. It was late.")) == 3
    # A digit opens a sentence just as a capital does.
    assert len(split_sentences("It cost five pounds. 1914 was the year. Then it ended.")) == 3


def test_a_dense_script_costs_more_of_the_budget():
    """300 Han characters is nothing like 300 Latin characters of speech."""
    from tertius.speech import spoken_length

    latin = "a" * 100
    assert spoken_length(latin) == 100
    # A hundred Han characters is roughly a hundred syllables.
    assert spoken_length("每" * 100) == 400
    # Mixed text is counted per character, not per string.
    assert spoken_length("ab每") == 2 + 4


def test_a_chinese_translation_is_not_one_giant_chunk():
    """Measured: one 326-character chunk produced 23.6s of truncated audio.

    Short Chinese still packs into one chunk, and should - the bug was never
    "always split", it was that nothing *could* split.
    """
    from tertius.speech import chunks_from_prose, spoken_length

    long_zh = ZH * 5  # about what a minute of devotional audio translates to
    assert spoken_length(long_zh) > 300, "sample must exceed the budget"

    chunks = chunks_from_prose(long_zh, "chatterbox-multilingual")
    assert len(chunks) > 1
    assert all(spoken_length(c.text) <= 300 for c in chunks)
    # Nothing dropped on the way through.
    assert "".join(c.text for c in chunks).count("。") == long_zh.count("。")


def test_the_translator_s_own_line_breaks_are_the_sentences(tmp_path):
    """It puts one sentence per line; re-splitting is a chance to get it wrong.

    And the lines are still packed, not spoken one at a time - a chunk per
    sentence would put a pause between every one and quadruple the calls.
    """
    from tertius.speech import chunks_from_prose

    prose = chr(10).join(f"Sentence number {n} goes here." for n in range(12))
    chunks = chunks_from_prose(prose, "chatterbox-multilingual")
    assert 1 < len(chunks) < 12
    # Nothing was lost in the packing.
    joined = " ".join(c.text for c in chunks)
    assert joined.count("Sentence number") == 12


# ------------------------------------------------------------- fitting on a card


def test_the_earlier_stages_give_back_the_gpu_before_speaking(api, tmp_path):
    """Three models do not fit on a 6 GB card, and the reading is the biggest.

    Measured: whisper large-v3-turbo 2.23 GB + m2m100-418M 0.27 GB +
    chatterbox-multilingual 3.22 GB = 5.72 GB, on a 6.44 GB card with a browser
    already holding a gigabyte. It failed with "CUDA out of memory" *after*
    writing the transcript and the translation.
    """
    audio = _queue_audio(api, tmp_path)

    api.manager.start(
        output_dir=api.output_dir,
        options={"translate": True, "target_language": "es", "speak": True},
    )
    api.wait_done()

    # Twice each: once to make room for the reading, once when the batch ends.
    # They reload themselves when the next file needs them.
    assert api.tertius is not None and api.tertius.unloads == 2
    assert api.translator is not None and api.translator.unloads == 2


def test_the_card_is_released_when_the_batch_ends(api, tmp_path, monkeypatch):
    """Unloading is not releasing.

    Dropping the Python reference leaves torch's caching allocator holding the
    blocks, so an idle server sits on the card until it is restarted - measured
    at 4,735 MiB fifteen hours after a job finished, on a 6 GB card. The next
    job then starts short of the memory it thinks it has, which is the likelier
    explanation for an out-of-memory failure than anything about the models.
    """
    from tertius.jobs import JobManager

    calls = []
    monkeypatch.setattr(
        JobManager, "_empty_cuda_cache", staticmethod(lambda: calls.append(1))
    )

    _queue_audio(api, tmp_path)
    api.manager.start(
        output_dir=api.output_dir,
        options={"translate": True, "target_language": "es", "speak": True},
    )
    api.wait_done()

    # Twice: once to make room for the reading, once when the batch ends.
    assert len(calls) == 2, calls


def test_the_card_is_released_when_a_model_will_not_load(api, tmp_path, monkeypatch):
    """The failure path is the one that most needs to let go of the card.

    These returns happen *before* the batch's try/finally, so whatever had
    already loaded stayed resident - and the next attempt started shorter
    still. That is the path an out-of-memory failure actually takes.
    """
    from tertius.jobs import JobManager

    calls = []
    monkeypatch.setattr(
        JobManager, "_empty_cuda_cache", staticmethod(lambda: calls.append(1))
    )

    _queue_audio(api, tmp_path)
    # Whisper loads, then the voice model refuses - so something is resident.
    api.speaker_load_error = RuntimeError("CUDA out of memory")
    api.manager.start(
        output_dir=api.output_dir,
        options={"translate": True, "target_language": "es", "speak": True},
    )
    api.wait_done()

    assert api.manager.status(include_files=False)["state"] == "error"
    assert calls, "the card was never released on the failure path"


def test_nothing_is_unloaded_when_the_work_is_on_the_cpu(api, tmp_path):
    """A reload costs real time; there is nothing to reclaim on the CPU."""
    audio = _queue_audio(api, tmp_path)
    api.cpu_only = True

    api.manager.start(
        output_dir=api.output_dir,
        options={
            "translate": True,
            "target_language": "es",
            "speak": True,
            "device": "cpu",
        },
    )
    api.wait_done()

    # Once only - the batch's own cleanup. Nothing was reclaimed mid-run,
    # because there is no VRAM to reclaim and a reload costs real time.
    assert api.tertius is not None and api.tertius.unloads == 1


def test_an_out_of_memory_failure_says_what_to_do_about_it(api, tmp_path):
    """The raw message is four lines of allocator statistics and no advice."""
    audio = _queue_audio(api, tmp_path)
    api.speaker_speak_error = RuntimeError(
        "CUDA out of memory. Tried to allocate 204.00 MiB. GPU 0 has a total "
        "capacity of 6.00 GiB of which 0 bytes is free."
    )

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

    notice = api.manager.status(include_files=False)["notice"] or ""
    assert "3.2 GB" in notice
    assert "Device to cpu" in notice
    # And the transcript it already wrote is still there.
    assert api.manager.store.get(audio)["status"] == "done"


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
