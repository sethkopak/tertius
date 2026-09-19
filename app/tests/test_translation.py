"""Translation: options, adapters, output naming, and what a failure costs.

Nothing here downloads or converts a model. The two adapters are tested against
a recording tokenizer rather than a real one, because what matters is the exact
token sequence each family needs - get that wrong and neither model errors, it
just translates into the wrong language.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tertius.config import TRANSLATION_MODELS, TranscriptionOptions
from tertius.transcribe import Segment, TranscriptionResult
from tertius.translate import (
    _M2M100Adapter,
    _T5Adapter,
    _source_code_for,
    converted_dir,
    is_converted,
    forget_cached_languages,
    supported_target_languages,
    translate_outputs,
    translate_text_file,
    translated_result,
)

from .fakes import FakeTranslator, make_audio


# --------------------------------------------------------------------- options


def test_translate_needs_a_target_language():
    with pytest.raises(ValueError, match="target language is required"):
        TranscriptionOptions(translate=True)


def test_target_language_is_not_required_when_not_translating():
    options = TranscriptionOptions(translate=False)
    assert options.target_language is None


def test_unknown_translation_model_is_rejected():
    with pytest.raises(ValueError, match="unknown translation model"):
        TranscriptionOptions(translation_model="nllb-200")


def test_nllb_is_not_offered():
    """The licence, not an oversight - see the note in config.py.

    NLLB-200 is the best model of its size and is CC-BY-NC-4.0. If someone adds
    it back, this test is where they have to argue with the reason.
    """
    repos = [entry["repo"] for entry in TRANSLATION_MODELS.values()]
    assert not any("nllb" in repo.lower() for repo in repos)
    for entry in TRANSLATION_MODELS.values():
        assert entry["license"] in {"MIT", "Apache-2.0"}


def test_target_language_is_trimmed_not_lowercased():
    # MADLAD has codes like `zh_Hant`, so lowercasing would break them - unlike
    # the Whisper `language` field just above it, which is lowercased on purpose.
    options = TranscriptionOptions(translate=True, target_language="  zh_Hant ")
    assert options.target_language == "zh_Hant"


def test_options_round_trip_through_a_dict():
    options = TranscriptionOptions(
        translate=True, target_language="es", translation_model="m2m100-1.2B"
    )
    again = TranscriptionOptions.from_dict(options.to_dict())
    assert again.translate is True
    assert again.target_language == "es"
    assert again.translation_model == "m2m100-1.2B"


# -------------------------------------------------------------------- adapters


class RecordingTokenizer:
    """Records what it was asked to encode; returns tokens we can assert on."""

    def __init__(self):
        self.src_lang = None
        self.encoded: list[str] = []
        self.lang_code_to_token = {"es": "__es__", "fr": "__fr__"}

    def encode(self, text):
        self.encoded.append(text)
        return [1, 2, 3]

    def convert_ids_to_tokens(self, ids):
        prefix = [f"__{self.src_lang}__"] if self.src_lang else []
        return prefix + ["a", "b", "c"]

    def convert_tokens_to_ids(self, tokens):
        return list(tokens)

    def decode(self, ids, skip_special_tokens=False):
        return " ".join(str(i) for i in ids)


def test_m2m100_puts_the_source_language_in_and_forces_the_target():
    tokenizer = RecordingTokenizer()
    adapter = _M2M100Adapter(tokenizer)

    tokens = adapter.encode("hola", "en")

    assert tokenizer.src_lang == "en"
    assert tokens[0] == "__en__"
    assert adapter.target_prefix("es") == ["__es__"]


def test_m2m100_drops_the_forced_language_token_from_the_output():
    """The target token is an instruction, not a word the model produced."""
    adapter = _M2M100Adapter(RecordingTokenizer())
    assert adapter.decode(["__es__", "hola", "mundo"]) == "hola mundo"


def test_t5_puts_the_target_in_the_text_and_forces_nothing():
    tokenizer = RecordingTokenizer()
    adapter = _T5Adapter(tokenizer)

    adapter.encode_for("hello", "es")

    assert tokenizer.encoded == ["<2es> hello"]
    assert adapter.target_prefix("es") is None


def test_t5_keeps_every_output_token():
    """MADLAD emits no language token, so dropping the first would eat a word."""
    adapter = _T5Adapter(RecordingTokenizer())
    assert adapter.decode(["hola", "mundo"]) == "hola mundo"


# ------------------------------------------------------------- language lists


def test_supported_languages_are_empty_until_the_model_is_converted(monkeypatch, tmp_path):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()
    assert supported_target_languages("m2m100-418M") == ()
    assert is_converted("m2m100-418M") is False


def test_supported_languages_are_read_from_the_converted_vocabulary(monkeypatch, tmp_path):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()
    directory = tmp_path / "m2m100-418M"
    directory.mkdir(parents=True)
    (directory / "shared_vocabulary.json").write_text(
        json.dumps(["hello", "__en__", "__es__", "__fr__", "<unk>"]), encoding="utf-8"
    )
    assert supported_target_languages("m2m100-418M") == ("en", "es", "fr")


def test_madlad_languages_use_its_own_token_shape(monkeypatch, tmp_path):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()
    directory = tmp_path / "madlad400-3B"
    directory.mkdir(parents=True)
    (directory / "shared_vocabulary.json").write_text(
        json.dumps(["<2es>", "<2zh_Hant>", "__en__", "word"]), encoding="utf-8"
    )
    # `__en__` is M2M-100's shape and must not be picked up here.
    assert supported_target_languages("madlad400-3B") == ("es", "zh_Hant")


def test_a_half_written_model_is_not_treated_as_converted(monkeypatch, tmp_path):
    """Weights without a tokenizer is what an interrupted conversion leaves."""
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    directory = tmp_path / "m2m100-418M"
    directory.mkdir(parents=True)
    (directory / "model.bin").write_bytes(b"weights")
    assert is_converted("m2m100-418M") is False
    (directory / "sentencepiece.bpe.model").write_bytes(b"tokenizer")
    assert is_converted("m2m100-418M") is True


def test_converted_dir_rejects_an_unknown_model():
    with pytest.raises(ValueError, match="unknown translation model"):
        converted_dir("no-such-model")


# --------------------------------------------------------- the source language


def test_an_unknown_source_language_falls_back_to_english(monkeypatch, tmp_path, caplog):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()
    directory = tmp_path / "m2m100-418M"
    directory.mkdir(parents=True)
    (directory / "shared_vocabulary.json").write_text(
        json.dumps(["__en__", "__es__"]), encoding="utf-8"
    )
    translator = FakeTranslator("m2m100-418M")
    # `haw` is a Whisper code that M2M-100 does not have.
    assert _source_code_for(translator, "haw") == "en"
    assert _source_code_for(translator, "es") == "es"


def test_madlad_is_never_told_the_source_language():
    translator = FakeTranslator("madlad400-3B")
    assert _source_code_for(translator, "es") == ""


# -------------------------------------------------------------------- results


def _result():
    return TranscriptionResult(
        segments=[Segment(0.0, 1.5, "hello there"), Segment(1.5, 3.0, "second bit")],
        language="en",
        duration=3.0,
    )


def test_translating_keeps_the_measured_timings():
    translated = translated_result(_result(), FakeTranslator(), "es")
    assert [(s.start, s.end) for s in translated.segments] == [(0.0, 1.5), (1.5, 3.0)]
    assert translated.segments[0].text == "[es] HELLO THERE"


def test_a_translation_records_where_it_came_from():
    translated = translated_result(_result(), FakeTranslator(), "es")
    assert translated.translation == {
        "model": "m2m100-418M",
        "repo": "facebook/m2m100_418M",
        "target_language": "es",
        "source_language": "en",
    }


def test_word_timings_do_not_survive_translation():
    """They describe the source words, which the translation has replaced."""
    from tertius.transcribe import TimedWord

    original = _result()
    original.words = [TimedWord("hello", 0.0, 0.5)]
    assert translated_result(original, FakeTranslator(), "es").words == []


def test_blank_segments_are_left_alone_not_sent_to_the_model():
    """An empty segment handed to a translator comes back as a hallucination."""
    original = TranscriptionResult(
        segments=[Segment(0.0, 1.0, "  "), Segment(1.0, 2.0, "real text")],
        language="en",
    )
    translated = translated_result(original, FakeTranslator(), "fr")
    assert translated.segments[0].text == "  "
    assert translated.segments[1].text == "[fr] REAL TEXT"


# -------------------------------------------------------------------- outputs


def test_the_translation_lands_beside_the_transcript(tmp_path):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    out = tmp_path / "out"

    from tertius.transcribe import write_outputs

    write_outputs(source, _result(), out, ["txt", "srt"])
    written, _ = translate_outputs(
        _result(), source, out, ["txt", "srt"], FakeTranslator(), "es"
    )

    assert (out / "talk.txt").is_file()
    assert (out / "talk.srt").is_file()
    assert (out / "talk.es.txt").is_file()
    assert {str(out / "talk.es.txt"), str(out / "talk.es.srt")} == set(written)
    # The original is untouched by the translation.
    assert "hello there" in (out / "talk.txt").read_text(encoding="utf-8")
    assert "[es] HELLO THERE" in (out / "talk.es.txt").read_text(encoding="utf-8")


def test_the_translated_srt_keeps_the_original_cue_times(tmp_path):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    out = tmp_path / "out"
    translate_outputs(_result(), source, out, ["srt"], FakeTranslator(), "es")
    srt = (out / "talk.es.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,500" in srt


def test_a_translated_json_says_it_is_a_translation(tmp_path):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    out = tmp_path / "out"
    translate_outputs(_result(), source, out, ["json"], FakeTranslator(), "es")

    payload = json.loads((out / "talk.es.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "translation"
    assert payload["translation"]["target_language"] == "es"
    assert payload["translation"]["repo"] == "facebook/m2m100_418M"


def test_an_ordinary_transcript_json_is_unchanged(tmp_path):
    """The new `kind` must not leak onto files that are not translations."""
    from tertius.transcribe import write_outputs

    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    out = tmp_path / "out"
    write_outputs(source, _result(), out, ["json"])
    payload = json.loads((out / "talk.json").read_text(encoding="utf-8"))
    assert payload["kind"] == "transcription"
    assert "translation" not in payload


# ------------------------------------------------------- through a whole job


def _run(api, tmp_path, *names, **option_overrides):
    """Queue some audio and run a batch to completion. Returns the status."""
    audio = tmp_path / "audio"
    made = make_audio(audio, *names)
    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    api.client.post("/api/queue", json={"files": scan["files"]})
    options = {
        "model_size": "tiny",
        "formats": ["txt"],
        "translate": True,
        "target_language": "es",
        **option_overrides,
    }
    res = api.client.post("/api/job/start", json={"options": options})
    if res.status_code != 200:
        return res
    api.wait_done()
    return made


def test_a_batch_writes_both_the_transcript_and_the_translation(api, tmp_path):
    _run(api, tmp_path, "talk.mp3")

    out = api.output_dir
    assert (out / "talk.txt").is_file()
    assert (out / "talk.es.txt").is_file()
    assert "[es] HELLO FROM TALK" in (out / "talk.es.txt").read_text(encoding="utf-8")
    assert api.translator.calls == [("es", "en")]
    # Released with the transcriber when the batch ends - a 3 GB translation
    # model must not sit in VRAM after the queue is empty.
    assert api.translator.loaded is False


def test_the_translated_file_is_recorded_as_an_output(api, tmp_path):
    _run(api, tmp_path, "talk.mp3")
    entry = api.client.get("/api/status").get_json()["files"][0]
    names = sorted(Path(p).name for p in entry["outputs"])
    assert names == ["talk.es.txt", "talk.txt"]


def test_nothing_is_translated_when_the_box_is_off(api, tmp_path):
    _run(api, tmp_path, "talk.mp3", translate=False, target_language=None)
    assert (api.output_dir / "talk.txt").is_file()
    assert not (api.output_dir / "talk.es.txt").exists()
    assert api.translator is None


def test_starting_without_a_target_language_is_refused(api, tmp_path):
    res = _run(api, tmp_path, "talk.mp3", target_language=None)
    assert res.status_code == 400
    assert "target language is required" in res.get_json()["error"]


def test_a_translator_that_cannot_load_stops_the_job_before_any_file(api, tmp_path):
    """Better to fail on Begin than after writing half a queue untranslated."""
    api.translator_load_error = RuntimeError("no torch here")

    _run(api, tmp_path, "a.mp3", "b.mp3")

    status = api.client.get("/api/status").get_json()
    assert status["state"] == "error"
    assert "translation is not available" in status["error"]
    assert "no torch here" in status["error"]
    # Nothing was transcribed, so nothing was written half-done.
    assert not (api.output_dir / "a.txt").exists()


def test_a_failed_translation_does_not_throw_away_the_transcript(api, tmp_path):
    """The transcript is real work and is already on disk - keep it.

    Marking the file failed would send a resume back to redo a transcription
    that was fine, which on a long recording costs an hour for a tokenizer bug.
    """
    api.translator_fails = True

    _run(api, tmp_path, "talk.mp3")

    status = api.client.get("/api/status").get_json()
    assert (api.output_dir / "talk.txt").is_file()
    assert not (api.output_dir / "talk.es.txt").exists()
    entry = status["files"][0]
    assert entry["status"] == "done"
    assert "could not be translated" in (status["notice"] or "")


def test_three_failed_translations_in_a_row_stop_the_batch(api, tmp_path):
    api.translator_fails = True

    _run(api, tmp_path, "a.mp3", "b.mp3", "c.mp3", "d.mp3")

    status = api.client.get("/api/status").get_json()
    assert status["state"] == "error"
    assert "could not be translated" in status["error"]
    # The three it got to are transcribed and kept; the fourth is untouched.
    assert (api.output_dir / "c.txt").is_file()
    assert not (api.output_dir / "d.txt").exists()


# ------------------------------------------------------------------- the API


def test_languages_endpoint_reports_an_unconverted_model(api, monkeypatch, tmp_path):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()

    body = api.client.get("/api/translation/languages?model=m2m100-418M").get_json()

    assert body["ready"] is False
    assert body["languages"] == []
    assert body["download_bytes"] == 1_940_000_000
    assert body["license"] == "MIT"


def test_languages_endpoint_lists_a_converted_model(api, monkeypatch, tmp_path):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()
    directory = tmp_path / "m2m100-418M"
    directory.mkdir(parents=True)
    (directory / "model.bin").write_bytes(b"weights")
    (directory / "sentencepiece.bpe.model").write_bytes(b"tokenizer")
    (directory / "shared_vocabulary.json").write_text(
        json.dumps(["__en__", "__es__"]), encoding="utf-8"
    )

    body = api.client.get("/api/translation/languages?model=m2m100-418M").get_json()

    assert body["ready"] is True
    assert body["languages"] == ["en", "es"]


def test_languages_endpoint_rejects_an_unknown_model(api):
    res = api.client.get("/api/translation/languages?model=nllb-200")
    assert res.status_code == 404


def test_the_page_offers_every_translation_model(api):
    page = api.client.get("/").get_data(as_text=True)
    for name in TRANSLATION_MODELS:
        assert name in page


# --------------------------------------------------- making a model ready


def test_a_model_can_be_prepared_without_starting_a_job(api):
    """The deadlock this endpoint exists to break.

    The target-language menu is filled from the converted model's vocabulary,
    and nothing converted a model except starting a job - which will not start
    without a target language. So no language could ever be chosen. Preparing a
    model must therefore need no options at all.
    """
    res = api.client.post("/api/translation/prepare", json={"model": "m2m100-418M"})
    assert res.status_code == 200
    api.wait_done()

    assert api.translator.prepared is True
    # Converting must not take a device: nobody has asked to run it yet.
    assert api.translator.loaded is False
    assert api.translator.device == "cpu"

    status = api.client.get("/api/status").get_json()
    assert status["state"] == "completed"
    assert "ready to translate" in (status["notice"] or "")


def test_preparing_defaults_to_the_default_model(api):
    api.client.post("/api/translation/prepare", json={})
    api.wait_done()
    assert api.translator.model_key == "m2m100-418M"


def test_preparing_an_unknown_model_is_refused(api):
    res = api.client.post("/api/translation/prepare", json={"model": "nllb-200"})
    assert res.status_code == 409
    assert "unknown translation model" in res.get_json()["error"]


def test_preparing_reports_a_failure_rather_than_hanging(api):
    api.translator_prepare_error = RuntimeError("no torch here")

    api.client.post("/api/translation/prepare", json={"model": "m2m100-418M"})
    api.wait_done()

    status = api.client.get("/api/status").get_json()
    assert status["state"] == "error"
    assert "could not prepare the translation model" in status["error"]
    assert "no torch here" in status["error"]


def test_preparing_while_a_job_runs_is_refused(api, tmp_path):
    audio = tmp_path / "audio"
    make_audio(audio, "talk.mp3")
    gate = api.block(audio / "talk.mp3")
    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    api.client.post("/api/queue", json={"files": scan["files"]})
    api.client.post("/api/job/start", json={"options": {"model_size": "tiny"}})

    try:
        res = api.client.post("/api/translation/prepare", json={"model": "m2m100-418M"})
        assert res.status_code == 409
        assert "already running" in res.get_json()["error"]
    finally:
        gate.set()


def test_the_page_offers_a_way_to_prepare_a_model(api):
    """Without this button there is no path to a language at all."""
    page = api.client.get("/").get_data(as_text=True)
    assert "btn-prepare-translation" in page


# ------------------------------------------------- text in, with no audio


def _text(directory, name, body):
    directory.mkdir(parents=True, exist_ok=True)
    path = directory / name
    path.write_text(body, encoding="utf-8")
    return path


def test_a_text_file_is_translated_with_no_audio_at_all(tmp_path):
    source = _text(tmp_path, "notes.txt", "First sentence. Second one.\n\nA new para.")
    written, result = translate_text_file(
        source, tmp_path / "out", FakeTranslator(), "es"
    )

    body = (tmp_path / "out" / "notes.es.txt").read_text(encoding="utf-8")
    assert "[es] FIRST SENTENCE." in body
    assert "[es] A NEW PARA." in body
    assert written == [str(tmp_path / "out" / "notes.es.txt")]
    assert result.translation["from_text"] is True


def test_paragraph_breaks_survive_translation(tmp_path):
    source = _text(tmp_path, "notes.txt", "One. Two.\n\nThree.")
    translate_text_file(source, tmp_path / "out", FakeTranslator(), "es")
    body = (tmp_path / "out" / "notes.es.txt").read_text(encoding="utf-8")
    blocks = [b for b in body.split("\n\n") if b.strip()]
    assert len(blocks) == 2
    assert blocks[0].count("\n") == 1  # two sentences, one per line


def test_no_srt_is_written_for_text_however_the_chips_are_set(tmp_path):
    """There are no timings, and inventing cues would be worse than none."""
    source = _text(tmp_path, "notes.txt", "Only a sentence.")
    written, _ = translate_text_file(
        source, tmp_path / "out", FakeTranslator(), "es", formats=("txt", "srt", "json")
    )
    assert not any(p.endswith(".srt") for p in written)
    assert (tmp_path / "out" / "notes.es.json").is_file()


def test_an_empty_text_file_is_an_error_not_an_empty_output(tmp_path):
    source = _text(tmp_path, "blank.txt", "   \n\n  ")
    with pytest.raises(ValueError, match="no text to translate"):
        translate_text_file(source, tmp_path / "out", FakeTranslator(), "es")


def test_scanning_for_text_finds_txt_and_not_audio(api, tmp_path):
    folder = tmp_path / "docs"
    make_audio(folder, "talk.mp3")
    _text(folder, "notes.txt", "Some text.")

    media = api.client.post("/api/scan", json={"directory": str(folder)}).get_json()
    text = api.client.post(
        "/api/scan", json={"directory": str(folder), "kind": "text"}
    ).get_json()

    assert [Path(f).name for f in media["files"]] == ["talk.mp3"]
    assert [Path(f).name for f in text["files"]] == ["notes.txt"]


def test_an_unknown_scan_kind_is_refused(api, tmp_path):
    res = api.client.post(
        "/api/scan", json={"directory": str(tmp_path), "kind": "pdf"}
    )
    assert res.status_code == 400
    assert "unknown source kind" in res.get_json()["error"]


def test_a_queued_text_file_is_marked_a_text_source(api, tmp_path):
    folder = tmp_path / "docs"
    _text(folder, "notes.txt", "Some text.")
    found = api.client.post(
        "/api/scan", json={"directory": str(folder), "kind": "text"}
    ).get_json()
    api.client.post("/api/queue", json={"files": found["files"]})

    entry = api.client.get("/api/status").get_json()["files"][0]
    # Just "a text source". What is done with it is a stage chosen at run time,
    # not something baked in when it was scanned.
    assert entry["mode"] == "text"


def test_a_text_only_batch_never_loads_whisper(api, tmp_path):
    """Downloading gigabytes of Whisper for a queue with no audio is absurd,
    and on a machine with a broken GPU it would fail a job that never needed one."""
    folder = tmp_path / "docs"
    _text(folder, "notes.txt", "One sentence here.")
    found = api.client.post(
        "/api/scan", json={"directory": str(folder), "kind": "text"}
    ).get_json()
    api.client.post("/api/queue", json={"files": found["files"]})

    api.client.post(
        "/api/job/start",
        json={
            "options": {
                "model_size": "tiny",
                "formats": ["txt"],
                "translate": True,
                "target_language": "es",
            }
        },
    )
    api.wait_done()

    assert api.tertius.warmed_up is False
    assert api.tertius.calls == []
    body = (api.output_dir / "notes.es.txt").read_text(encoding="utf-8")
    assert "[es] ONE SENTENCE HERE." in body


def test_a_text_file_is_not_translated_twice(api, tmp_path):
    """It is translated by the text path; the post-step must leave it alone."""
    folder = tmp_path / "docs"
    _text(folder, "notes.txt", "One sentence here.")
    found = api.client.post(
        "/api/scan", json={"directory": str(folder), "kind": "text"}
    ).get_json()
    api.client.post("/api/queue", json={"files": found["files"]})
    api.client.post(
        "/api/job/start",
        json={
            "options": {
                "formats": ["txt"],
                "translate": True,
                "target_language": "es",
            }
        },
    )
    api.wait_done()

    body = (api.output_dir / "notes.es.txt").read_text(encoding="utf-8")
    assert "[es] [ES]" not in body
    assert not (api.output_dir / "notes.es.es.txt").exists()


def test_queued_text_with_translation_off_says_so(api, tmp_path):
    folder = tmp_path / "docs"
    _text(folder, "notes.txt", "One sentence here.")
    found = api.client.post(
        "/api/scan", json={"directory": str(folder), "kind": "text"}
    ).get_json()
    api.client.post("/api/queue", json={"files": found["files"]})

    api.client.post(
        "/api/job/start", json={"options": {"formats": ["txt"], "translate": False}}
    )
    api.wait_done()

    entry = api.client.get("/api/status").get_json()["files"][0]
    assert entry["status"] == "failed"
    # Both stages are named, because either one would give it something to do.
    assert "neither Translate nor Read aloud" in entry["error"]


def test_the_page_offers_the_source_switch(api):
    """Choosing the source is its own control now, not a translation setting.

    It used to be a checkbox inside the translation block reading "Translate
    text files, not audio", which made the kind of file and the stage applied
    to it one choice - so a text file could be translated or read aloud but
    never both.
    """
    page = api.client.get("/").get_data(as_text=True)
    assert 'data-source="media"' in page
    assert 'data-source="text"' in page
    assert "opt-text-source" not in page


# ----------------------------------------------- installing what it needs


def test_nothing_is_installed_when_it_is_all_already_there(monkeypatch):
    from tertius import translate as T

    monkeypatch.setattr(T, "missing_requirements", lambda: [])
    monkeypatch.setattr(
        T.subprocess, "Popen", lambda *a, **k: pytest.fail("should not have run pip")
    )
    assert T.install_requirements() == []


def test_torch_is_installed_from_the_cpu_index_and_on_its_own(monkeypatch):
    """The default PyPI wheel carries a bundled CUDA runtime on Linux and is
    an order of magnitude bigger. Conversion never runs the model, so the CPU
    build is all that is ever needed - and the other packages are not on that
    index, so they cannot share the call."""
    from tertius import translate as T

    calls: list[list[str]] = []

    class FakeProcess:
        stdout = iter(("Collecting torch", "Successfully installed torch"))

        def wait(self):
            return 0

    def fake_popen(command, **kwargs):
        calls.append(command)
        return FakeProcess()

    seen = iter([["torch", "transformers", "sentencepiece"], []])
    monkeypatch.setattr(T, "missing_requirements", lambda: next(seen))
    monkeypatch.setattr(T, "_in_a_virtualenv", lambda: True)
    monkeypatch.setattr(T.subprocess, "Popen", fake_popen)

    installed = T.install_requirements()

    assert installed == ["torch", "transformers", "sentencepiece"]
    assert len(calls) == 2
    assert calls[0][-3:] == ["--index-url", T.TORCH_CPU_INDEX, "torch"]
    assert calls[1][-2:] == ["transformers", "sentencepiece"]
    assert "torch" not in calls[1]


def test_it_refuses_to_install_into_a_system_python(monkeypatch):
    """Putting 120 MB of torch into someone's system Python because they
    clicked a button in a transcription app is not a thing to do."""
    from tertius import translate as T

    monkeypatch.setattr(T, "missing_requirements", lambda: ["torch"])
    monkeypatch.setattr(T, "_in_a_virtualenv", lambda: False)
    monkeypatch.setattr(
        T.subprocess, "Popen", lambda *a, **k: pytest.fail("should not have run pip")
    )

    with pytest.raises(T.TranslationUnavailableError, match="not running in a virtual"):
        T.install_requirements()


def test_a_failed_install_says_so_rather_than_carrying_on(monkeypatch):
    from tertius import translate as T

    class FailingProcess:
        stdout = iter(("ERROR: no matching distribution",))

        def wait(self):
            return 1

    monkeypatch.setattr(T, "missing_requirements", lambda: ["torch"])
    monkeypatch.setattr(T, "_in_a_virtualenv", lambda: True)
    monkeypatch.setattr(T.subprocess, "Popen", lambda *a, **k: FailingProcess())

    with pytest.raises(T.TranslationUnavailableError, match="could not install"):
        T.install_requirements()


def test_an_install_that_does_not_take_is_not_reported_as_success(monkeypatch):
    """pip exiting 0 without the import working is a real failure mode."""
    from tertius import translate as T

    class FakeProcess:
        stdout = iter(())

        def wait(self):
            return 0

    monkeypatch.setattr(T, "missing_requirements", lambda: ["transformers"])
    monkeypatch.setattr(T, "_in_a_virtualenv", lambda: True)
    monkeypatch.setattr(T.subprocess, "Popen", lambda *a, **k: FakeProcess())

    with pytest.raises(T.TranslationUnavailableError, match="still cannot import"):
        T.install_requirements()


def test_transcribing_never_installs_anything(api, tmp_path, monkeypatch):
    """The install happens on Download and prepare, and nowhere else.

    A transcription-only run must not reach for pip: someone who never asked to
    translate should not find 120 MB of torch in their environment.
    """
    from tertius import translate as T

    called: list[str] = []
    monkeypatch.setattr(
        T, "install_requirements", lambda *a, **k: called.append("installed") or []
    )

    audio = tmp_path / "audio"
    make_audio(audio, "talk.mp3")
    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    api.client.post("/api/queue", json={"files": scan["files"]})
    api.client.post("/api/job/start", json={"options": {"formats": ["txt"]}})
    api.wait_done()

    assert (api.output_dir / "talk.txt").is_file()
    assert called == []


def test_preparing_a_model_does_install(monkeypatch, tmp_path):
    """The other half of the rule above: prepare is what is allowed to."""
    from tertius import translate as T

    called: list[str] = []
    monkeypatch.setattr(
        T, "install_requirements", lambda *a, **k: called.append("installed") or []
    )
    monkeypatch.setattr(
        T, "ensure_translation_model", lambda key, progress=None: tmp_path
    )

    T.Translator("m2m100-418M").prepare()

    assert called == ["installed"]


# ------------------------------------------- what the converter is handed


def test_the_converter_is_never_handed_a_file_it_writes_itself(monkeypatch, tmp_path):
    """Regression: conversion died after the whole 1.9 GB download.

    `config.json` was in the copy list and CTranslate2 writes its own, so it
    stopped with "already exists in the model directory" - at the one point
    where failing costs the user everything they just waited for.
    """
    from tertius import translate as T
    from tertius.config import TRANSLATION_FILE_PATTERNS

    for family, patterns in TRANSLATION_FILE_PATTERNS.items():
        copied = [
            name
            for name in patterns
            if not name.endswith((".bin", ".safetensors"))
            and name not in T.CONVERTER_WRITES
        ]
        assert "config.json" not in copied, family
        assert not (set(copied) & T.CONVERTER_WRITES), family
        # The tokenizer still has to arrive, or the converted model is unusable.
        assert any("token" in n or "piece" in n or "vocab" in n for n in copied), family


def test_every_family_names_its_tokenizer_class():
    """`AutoTokenizer` cannot be trusted on a converted directory: `config.json`
    there is CTranslate2's runtime config, and M2M-100 names no tokenizer_class."""
    from tertius.config import TRANSLATION_MODELS
    from tertius.translate import TOKENIZER_CLASSES

    families = {entry["family"] for entry in TRANSLATION_MODELS.values()}
    assert families <= set(TOKENIZER_CLASSES)


def test_an_empty_language_list_is_never_cached(monkeypatch, tmp_path):
    """A model prepared by another process must be seen without a restart."""
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    forget_cached_languages()

    assert supported_target_languages("m2m100-418M") == ()

    directory = tmp_path / "m2m100-418M"
    directory.mkdir(parents=True)
    (directory / "shared_vocabulary.json").write_text(
        json.dumps(["__en__", "__es__"]), encoding="utf-8"
    )

    # No cache_clear in between: the empty answer must not have stuck.
    assert supported_target_languages("m2m100-418M") == ("en", "es")


# --------------------------------------- sentences for reading, segments for timing


def _fragmented():
    """A transcript cut the way Whisper cuts: mid-sentence, no full stops."""
    return TranscriptionResult(
        segments=[
            Segment(0.0, 1.0, "The doubt and gloom"),
            Segment(1.0, 2.0, "intensified by the darkness"),
            Segment(2.0, 3.0, "were lifted at last. A new day"),
            Segment(3.0, 4.0, "had begun."),
        ],
        language="en",
    )


def test_the_txt_is_translated_as_sentences_not_fragments(tmp_path):
    """The whole point: the model must never be handed 'intensified by' alone."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()

    translate_outputs(
        _fragmented(), source, tmp_path / "out", ["txt"], translator, "es"
    )

    assert len(translator.batches) == 1
    given = translator.batches[0]
    assert given == [
        "The doubt and gloom intensified by the darkness were lifted at last.",
        "A new day had begun.",
    ]


def test_the_srt_is_still_translated_segment_by_segment(tmp_path):
    """Timings belong to segments, and only a segment has them."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()

    translate_outputs(
        _fragmented(), source, tmp_path / "out", ["srt"], translator, "es"
    )

    assert len(translator.batches) == 1
    assert translator.batches[0] == [
        "The doubt and gloom",
        "intensified by the darkness",
        "were lifted at last. A new day",
        "had begun.",
    ]
    srt = (tmp_path / "out" / "talk.es.srt").read_text(encoding="utf-8")
    assert "00:00:00,000 --> 00:00:01,000" in srt


def test_both_passes_run_when_both_formats_are_wanted(tmp_path):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()

    translate_outputs(
        _fragmented(), source, tmp_path / "out", ["txt", "srt"], translator, "es"
    )

    assert len(translator.batches) == 2
    # Four segments one way, two sentences the other.
    assert sorted(len(b) for b in translator.batches) == [2, 4]


def test_a_txt_only_run_never_translates_twice(tmp_path):
    """It used to translate a second time purely to build a return value."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()

    _, result = translate_outputs(
        _fragmented(), source, tmp_path / "out", ["txt"], translator, "es"
    )

    assert len(translator.batches) == 1
    assert result.translation["target_language"] == "es"


def test_the_translated_txt_has_one_sentence_per_line(tmp_path):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translate_outputs(
        _fragmented(), source, tmp_path / "out", ["txt"], FakeTranslator(), "es"
    )
    lines = [
        line
        for line in (tmp_path / "out" / "talk.es.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    assert len(lines) == 2


def test_the_json_keeps_the_segment_level_translation(tmp_path):
    """It is the shape with timings in it; sentences have none."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translate_outputs(
        _fragmented(), source, tmp_path / "out", ["json"], FakeTranslator(), "es"
    )
    payload = json.loads(
        (tmp_path / "out" / "talk.es.json").read_text(encoding="utf-8")
    )
    assert len(payload["segments"]) == 4
    assert payload["segments"][0]["end"] == 1.0


# ------------------------------------------------------ gating the second pass


def test_the_sentence_pass_is_on_by_default():
    """An unreadable `.txt` is the thing `.txt` exists to avoid."""
    assert TranscriptionOptions().translate_sentences is True


def test_turning_it_off_translates_once_and_the_txt_comes_from_segments(tmp_path):
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()

    translate_outputs(
        _fragmented(),
        source,
        tmp_path / "out",
        ["txt", "srt"],
        translator,
        "es",
        sentence_pass=False,
    )

    assert len(translator.batches) == 1
    assert len(translator.batches[0]) == 4  # the segments, not the sentences
    lines = [
        line
        for line in (tmp_path / "out" / "talk.es.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip()
    ]
    # Rendered from segments, so it is the run-on version this setting buys out of.
    assert len(lines) < 4


def test_the_srt_is_identical_whichever_way_the_setting_goes(tmp_path):
    """The setting must not touch the timed output. That is the whole promise."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")

    translate_outputs(
        _fragmented(), source, tmp_path / "a", ["srt"], FakeTranslator(), "es",
        sentence_pass=True,
    )
    translate_outputs(
        _fragmented(), source, tmp_path / "b", ["srt"], FakeTranslator(), "es",
        sentence_pass=False,
    )

    assert (tmp_path / "a" / "talk.es.srt").read_text(encoding="utf-8") == (
        tmp_path / "b" / "talk.es.srt"
    ).read_text(encoding="utf-8")


def test_an_srt_only_run_never_pays_for_the_second_pass(tmp_path):
    """No `.txt` was asked for, so the setting costs nothing either way."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()

    translate_outputs(
        _fragmented(), source, tmp_path / "out", ["srt"], translator, "es",
        sentence_pass=True,
    )

    assert len(translator.batches) == 1


def test_the_setting_reaches_the_translator_through_a_job(api, tmp_path):
    audio = tmp_path / "audio"
    make_audio(audio, "talk.mp3")
    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    api.client.post("/api/queue", json={"files": scan["files"]})
    api.client.post(
        "/api/job/start",
        json={
            "options": {
                "formats": ["txt"],
                "translate": True,
                "target_language": "es",
                "translate_sentences": False,
            }
        },
    )
    api.wait_done()

    status = api.client.get("/api/status").get_json()
    assert status["options"]["translate_sentences"] is False
    assert (api.output_dir / "talk.es.txt").is_file()


def test_the_page_offers_the_sentence_setting(api):
    page = api.client.get("/").get_data(as_text=True)
    assert "opt-translate-sentences" in page


# ------------------------------------------------- saying that it is translating


def test_the_translator_reports_progress(tmp_path):
    """Minutes of one silent call is indistinguishable from a hang."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()
    seen: list[tuple[int, int]] = []

    translate_outputs(
        _fragmented(),
        source,
        tmp_path / "out",
        ["srt"],
        translator,
        "es",
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen == [(4, 4)]


def test_progress_spans_both_passes_and_only_goes_up(tmp_path):
    """A bar that restarts half way looks broken; one that goes back looks worse."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    seen: list[tuple[int, int]] = []

    translate_outputs(
        _fragmented(),
        source,
        tmp_path / "out",
        ["txt", "srt"],
        FakeTranslator(),
        "es",
        on_progress=lambda done, total: seen.append((done, total)),
    )

    # Four segments then two sentences, counted against one total of six.
    assert seen == [(4, 6), (6, 6)]
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)
    assert len({total for _, total in seen}) == 1


def test_a_job_moves_the_file_progress_while_translating(api, tmp_path):
    audio = tmp_path / "audio"
    make_audio(audio, "talk.mp3")
    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    api.client.post("/api/queue", json={"files": scan["files"]})
    api.client.post(
        "/api/job/start",
        json={
            "options": {
                "formats": ["srt"],
                "translate": True,
                "target_language": "es",
            }
        },
    )
    api.wait_done()

    # The fake reports once per call; what matters is that the manager accepted
    # it, which it only does through the on_progress keyword being passed.
    assert api.translator.progress == [(2, 2)]


# ------------------------------------------------- saying that it is translating


def test_the_translator_reports_progress(tmp_path):
    """Minutes of one silent call is indistinguishable from a hang."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    translator = FakeTranslator()
    seen: list[tuple[int, int]] = []

    translate_outputs(
        _fragmented(),
        source,
        tmp_path / "out",
        ["srt"],
        translator,
        "es",
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen == [(4, 4)]


def test_progress_spans_both_passes_and_only_goes_up(tmp_path):
    """A bar that restarts half way looks broken; one that goes back looks worse."""
    source = tmp_path / "talk.mp3"
    source.write_bytes(b"\x00")
    seen: list[tuple[int, int]] = []

    translate_outputs(
        _fragmented(),
        source,
        tmp_path / "out",
        ["txt", "srt"],
        FakeTranslator(),
        "es",
        on_progress=lambda done, total: seen.append((done, total)),
    )

    # Four segments then two sentences, counted against one total of six.
    assert seen == [(4, 6), (6, 6)]
    assert [d for d, _ in seen] == sorted(d for d, _ in seen)
    assert len({total for _, total in seen}) == 1


def test_a_job_passes_the_progress_callback_through(api, tmp_path):
    audio = tmp_path / "audio"
    make_audio(audio, "talk.mp3")
    scan = api.client.post("/api/scan", json={"directory": str(audio)}).get_json()
    api.client.post("/api/queue", json={"files": scan["files"]})
    api.client.post(
        "/api/job/start",
        json={
            "options": {
                "formats": ["srt"],
                "translate": True,
                "target_language": "es",
            }
        },
    )
    api.wait_done()

    # The fake only records this when it is given the keyword, so a non-empty
    # list is the manager actually wiring its reporter in.
    assert api.translator.progress == [(2, 2)]


# --------------------------------------------------- the model comparison table


def test_the_models_endpoint_lists_every_model(api, monkeypatch, tmp_path):
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)

    body = api.client.get("/api/translation/models").get_json()

    assert [m["model"] for m in body["models"]] == list(TRANSLATION_MODELS)
    for entry in body["models"]:
        assert entry["ready"] is False
        assert entry["disk_bytes"] is None
        assert entry["download_bytes"] > 0
        assert entry["license"] in {"MIT", "Apache-2.0"}
        assert entry["languages"] > 0


def test_the_models_endpoint_measures_what_is_on_disk(api, monkeypatch, tmp_path):
    """Measured, not predicted: int8 makes the converted size a fraction of
    the download, and the ratio is not worth guessing at."""
    monkeypatch.setattr("tertius.translate.cache_root", lambda: tmp_path)
    directory = tmp_path / "m2m100-418M"
    directory.mkdir(parents=True)
    (directory / "model.bin").write_bytes(b"x" * 5000)
    (directory / "sentencepiece.bpe.model").write_bytes(b"y" * 500)

    body = api.client.get("/api/translation/models").get_json()
    entry = next(m for m in body["models"] if m["model"] == "m2m100-418M")

    assert entry["ready"] is True
    assert entry["disk_bytes"] == 5500


def test_the_page_has_an_info_button_for_the_translators(api):
    page = api.client.get("/").get_data(as_text=True)
    assert "btn-translation-info" in page
    assert "panel-translation-info" in page
    assert "translation-table" in page
