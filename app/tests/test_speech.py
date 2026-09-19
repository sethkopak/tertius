"""Reading a text file aloud: the markup, the writer, and the queue.

Nothing here downloads a model or generates a sample of real audio. The model
is a fake that returns a flat run of samples proportional to the text, which is
enough to prove every timing claim the feature makes - the `.srt` is measured
against audio that was actually written, not estimated, and a fake writes real
frames just as a model does.
"""

from __future__ import annotations

import json
import wave
from pathlib import Path

import pytest

from tertius.config import (
    SPEECH_GAP_SECONDS,
    SPEECH_PARAGRAPH_GAP_SECONDS,
    TranscriptionOptions,
)
from tertius.speech import (
    WavWriter,
    parse_script,
    resolve_style,
    speak_text_file,
    style_params,
)
from tertius.state import (
    MODE_TEXT,
    MODE_TRANSCRIBE,
    MODE_TRANSLATE_TEXT,
    StateStore,
)

from .fakes import FakeSpeaker, wait_until

MTL = "chatterbox-multilingual"
TURBO = "chatterbox-turbo"


def script_for(text, model=MTL, style="neutral"):
    return parse_script(text, model, style)


# ---------------------------------------------------------------- the markup


def test_a_style_tag_is_stripped_and_changes_what_follows():
    script = script_for("[solemn] In the beginning was the Word.")
    assert len(script.chunks) == 1
    assert script.chunks[0].text == "In the beginning was the Word."
    assert script.chunks[0].style == "solemn"
    assert "[solemn]" not in script.chunks[0].text


def test_a_style_tag_holds_until_the_next_one():
    script = script_for(
        "[solemn] First one. Second one.\n\n"
        "Still solemn, in a new paragraph.\n\n"
        "[bright] Now bright."
    )
    styles = [chunk.style for chunk in script.chunks]
    assert styles[:-1] == ["solemn"] * (len(styles) - 1)
    assert styles[-1] == "bright"


def test_the_default_style_applies_until_a_tag_says_otherwise():
    script = script_for("No tag here at all.", style="calm")
    assert script.chunks[0].style == "calm"


def test_an_unknown_bracket_stays_in_the_text_and_is_reported():
    """The `[inaudible]` case. Eating it would corrupt real transcripts."""
    script = script_for("He said [inaudible] and left.")
    assert script.chunks[0].text == "He said [inaudible] and left."
    assert any("[inaudible]" in w for w in script.warnings)
    assert any("not a style tag" in w for w in script.warnings)


def test_a_misspelt_style_tag_is_visible_rather_than_spoken_silently():
    script = script_for("[emphatc] Listen.")
    # Still in the text - it will be read out - but the warning says so and
    # lists what the real styles are.
    assert "[emphatc]" in script.chunks[0].text
    assert any("emphatic" in w for w in script.warnings)


def test_an_emotion_word_is_accepted_as_an_alias_and_warned_about():
    script = script_for("[angry] Get out.")
    assert script.chunks[0].style == "urgent"
    assert any("no emotion conditioning" in w for w in script.warnings)


def test_resolve_style_reports_the_alias_it_used():
    style, warning = resolve_style("excited")
    assert style == "bright"
    assert warning and "[excited]" in warning and "[bright]" in warning

    style, warning = resolve_style("calm")
    assert (style, warning) == ("calm", None)

    # Not a style and not an alias: the caller falls back rather than raising,
    # because the tag is still going to be read out as text.
    assert resolve_style("banana")[0] == "neutral"


def test_paralinguistic_tags_pass_through_on_turbo():
    script = script_for("Hello there [laugh] good to see you.", model=TURBO)
    assert "[laugh]" in script.chunks[0].text
    assert script.warnings == []


def test_paralinguistic_tags_are_removed_on_the_multilingual_model():
    """Left in, this model would read out the word "laugh"."""
    script = script_for("Hello there [laugh] good to see you.", model=MTL)
    assert "[laugh]" not in script.chunks[0].text
    assert any("was removed" in w for w in script.warnings)


def test_removing_a_tag_does_not_split_the_sentence_around_it():
    """A removed tag must not leave a chunk boundary, and so a pause, behind.

    The bug this pins: text either side of a dropped `[laugh]` was flushed as
    two separate runs, so one sentence was generated as two calls with a gap
    inserted between them that nobody wrote.
    """
    script = script_for("Hello there [laugh] good to see you.", model=MTL)
    assert len(script.chunks) == 1
    assert script.chunks[0].text == "Hello there good to see you."


def test_a_bracketed_phrase_with_spaces_is_never_a_tag():
    text = "He said [name unclear] and left."
    script = script_for(text)
    assert script.chunks[0].text == text
    assert script.warnings == []


def test_a_blank_line_marks_a_paragraph_and_a_style_change_does_not():
    script = script_for("First para.\n\nSecond para. [bright] Same para.")
    starts = [chunk.starts_paragraph for chunk in script.chunks]
    assert starts[0] is True
    assert starts[1] is True
    # The chunk after the mid-paragraph style tag must not claim a paragraph
    # break, or a pause appears where the writer put none.
    assert starts[2] is False


def test_sentences_are_packed_up_to_the_budget():
    text = " ".join(f"Sentence number {n}." for n in range(1, 21))
    script = script_for(text)
    assert len(script.chunks) > 1
    assert all(len(chunk.text) <= 300 for chunk in script.chunks)


def test_a_sentence_longer_than_the_budget_is_still_sent_whole():
    """Cutting mid-clause to satisfy a number puts a breath inside a thought."""
    long_one = "This is one very long sentence " + ("and it keeps going " * 40) + "."
    script = script_for(long_one)
    assert len(script.chunks) == 1
    assert len(script.chunks[0].text) > 300


def test_empty_text_produces_no_chunks():
    assert script_for("   \n\n  ").chunks == []


# ------------------------------------------------------------- style numbers


def test_styles_are_deltas_from_each_model_s_own_baseline():
    """`[neutral]` must not mean two different things on two models."""
    assert style_params(MTL, "neutral") == {
        "exaggeration": 0.5,
        "cfg_weight": 0.5,
        "temperature": 0.8,
    }
    assert style_params(TURBO, "neutral") == {
        "exaggeration": 0.0,
        "cfg_weight": 0.0,
        "temperature": 0.8,
    }


def test_style_deltas_are_clamped_rather_than_going_negative():
    # Turbo's baseline is 0.0, and `calm` is -0.15 from it.
    assert style_params(TURBO, "calm")["exaggeration"] == 0.0
    assert style_params(TURBO, "urgent")["cfg_weight"] == 0.0


def test_pushing_a_style_raises_intensity_and_loosens_the_guidance():
    calm = style_params(MTL, "calm")
    urgent = style_params(MTL, "urgent")
    assert urgent["exaggeration"] > calm["exaggeration"]
    assert urgent["cfg_weight"] < calm["cfg_weight"]


def test_an_unknown_style_is_rejected():
    with pytest.raises(ValueError):
        style_params(MTL, "furious")


# -------------------------------------------------------------- the wav file


def read_wav(path):
    with wave.open(str(path), "rb") as handle:
        return {
            "channels": handle.getnchannels(),
            "width": handle.getsampwidth(),
            "rate": handle.getframerate(),
            "frames": handle.getnframes(),
        }


def test_the_writer_produces_a_readable_wav(tmp_path):
    target = tmp_path / "out.wav"
    with WavWriter(target, 1000) as writer:
        writer.append([0.5] * 1000)
        writer.silence(0.5)
        writer.append([-0.5] * 500)

    info = read_wav(target)
    assert info == {"channels": 1, "width": 2, "rate": 1000, "frames": 2000}


def test_the_writer_reports_its_position_in_seconds(tmp_path):
    with WavWriter(tmp_path / "out.wav", 1000) as writer:
        assert writer.append([0.0] * 2500) == 2.5
        assert writer.silence(0.5) == 3.0


def test_samples_are_clipped_rather_than_wrapping(tmp_path):
    """A value above 1.0 wrapped into int16 is a loud click, not a loud sample."""
    target = tmp_path / "out.wav"
    with WavWriter(target, 1000) as writer:
        writer.append([3.0, -3.0])
    with wave.open(str(target), "rb") as handle:
        frames = handle.readframes(2)
    import struct

    assert struct.unpack("<hh", frames) == (32767, -32767)


def test_an_abandoned_write_leaves_nothing_behind(tmp_path):
    target = tmp_path / "out.wav"
    writer = WavWriter(target, 1000)
    writer.append([0.1] * 100)
    writer.abandon()
    assert not target.exists()
    assert list(tmp_path.glob("*.partial")) == []


def test_a_failure_mid_reading_leaves_no_half_file(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("One. Two. Three.", encoding="utf-8")
    speaker = FakeSpeaker()
    speaker.fail_always = True
    with pytest.raises(RuntimeError):
        speak_text_file(source, tmp_path / "out", speaker, "en")
    assert list((tmp_path / "out").glob("*")) == []


# ----------------------------------------------------------- the whole file


def test_reading_a_file_writes_audio_and_matching_cues(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("First sentence. Second sentence.", encoding="utf-8")
    out = tmp_path / "out"

    written, result = speak_text_file(
        source, out, FakeSpeaker(), "en", formats=("srt", "json")
    )

    names = sorted(Path(p).name for p in written)
    assert names == ["talk.json", "talk.srt", "talk.wav"]
    # The text is the input; writing a near-copy back would be one more file to
    # tell apart from the one the user wrote.
    assert not (out / "talk.txt").exists()

    info = read_wav(out / "talk.wav")
    assert info["frames"] > 0
    # Every cue's end is inside the recording, because both were measured in
    # the same pass.
    assert result.segments
    assert result.segments[-1].end == pytest.approx(
        info["frames"] / info["rate"], abs=0.001
    )


def test_the_cues_describe_the_audio_that_was_written(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("First sentence.\n\nSecond paragraph here.", encoding="utf-8")
    out = tmp_path / "out"
    speaker = FakeSpeaker()

    _written, result = speak_text_file(source, out, speaker, "en", formats=("srt",))

    first, second = result.segments
    spoken = len(first.text) / (speaker.sample_rate / speaker.SAMPLES_PER_CHARACTER)
    assert first.start == 0.0
    assert first.end == pytest.approx(spoken, abs=0.001)
    # A paragraph break buys the longer pause.
    assert second.start - first.end == pytest.approx(
        SPEECH_PARAGRAPH_GAP_SECONDS, abs=0.01
    )


def test_chunks_inside_a_paragraph_get_the_shorter_gap(tmp_path):
    source = tmp_path / "talk.txt"
    # Long enough to be packed into more than one chunk, with no blank line.
    source.write_text(" ".join(f"Sentence {n} here." for n in range(40)), "utf-8")
    out = tmp_path / "out"

    _written, result = speak_text_file(source, out, FakeSpeaker(), "en")

    assert len(result.segments) > 1
    gap = result.segments[1].start - result.segments[0].end
    assert gap == pytest.approx(SPEECH_GAP_SECONDS, abs=0.01)


def test_the_json_says_it_is_a_reading_not_a_transcript(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("[solemn] Words that nobody said.", encoding="utf-8")
    out = tmp_path / "out"

    speak_text_file(source, out, FakeSpeaker(), "en", formats=("json",))
    payload = json.loads((out / "talk.json").read_text(encoding="utf-8"))

    assert payload["kind"] == "speech"
    assert payload["speech"]["model"] == MTL
    assert payload["speech"]["styles_used"] == ["solemn"]
    assert payload["speech"]["watermarked"] is True


def test_the_json_records_what_was_silently_changed(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("Hello [laugh] there.", encoding="utf-8")
    out = tmp_path / "out"

    speak_text_file(source, out, FakeSpeaker(), "en", formats=("json",))
    payload = json.loads((out / "talk.json").read_text(encoding="utf-8"))

    # Not recoverable from the audio afterwards, so it goes in the record.
    assert any("was removed" in w for w in payload["speech"]["warnings"])


def test_the_style_reaches_the_model_as_numbers(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("[calm] Soft line.\n\n[urgent] Loud line.", encoding="utf-8")
    speaker = FakeSpeaker()

    speak_text_file(source, tmp_path / "out", speaker, "en")

    calm, urgent = speaker.params
    assert urgent["exaggeration"] > calm["exaggeration"]
    assert [style for _text, style, _lang, _voice in speaker.calls] == [
        "calm",
        "urgent",
    ]


def test_the_voice_clip_is_passed_through(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("Read this.", encoding="utf-8")
    speaker = FakeSpeaker()

    speak_text_file(source, tmp_path / "out", speaker, "es", voice="C:/clip.wav")

    _text, _style, language, voice = speaker.calls[0]
    assert (language, voice) == ("es", "C:/clip.wav")


def test_a_byte_order_mark_is_not_read_out_loud(tmp_path):
    """Notepad writes a BOM; as plain utf-8 it sticks to the first word."""
    source = tmp_path / "talk.txt"
    source.write_bytes("\ufeffIn the beginning.".encode("utf-8"))
    speaker = FakeSpeaker()

    speak_text_file(source, tmp_path / "out", speaker, "en")

    assert speaker.calls[0][0] == "In the beginning."


def test_a_language_the_model_cannot_speak_is_refused(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("Hello.", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot speak"):
        speak_text_file(source, tmp_path / "out", FakeSpeaker(), "cy")


def test_turbo_only_speaks_english(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("Hello.", encoding="utf-8")
    with pytest.raises(ValueError, match="cannot speak"):
        speak_text_file(source, tmp_path / "out", FakeSpeaker(TURBO), "es")


def test_a_file_with_nothing_to_say_is_an_error_not_an_empty_wav(tmp_path):
    source = tmp_path / "blank.txt"
    source.write_text("\n\n   \n", encoding="utf-8")
    with pytest.raises(ValueError, match="no text"):
        speak_text_file(source, tmp_path / "out", FakeSpeaker(), "en")


def test_progress_is_reported_per_chunk(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text(" ".join(f"Sentence {n} here." for n in range(40)), "utf-8")
    seen: list[tuple[int, int]] = []

    speak_text_file(
        source,
        tmp_path / "out",
        FakeSpeaker(),
        "en",
        on_progress=lambda done, total: seen.append((done, total)),
    )

    assert seen
    assert seen[-1][0] == seen[-1][1]
    assert [done for done, _ in seen] == sorted(done for done, _ in seen)


# --------------------------------------------------------------- the options


def test_an_emotion_word_is_resolved_when_the_options_are_built():
    """Stored options must say what will actually happen, not what was typed."""
    assert TranscriptionOptions(speech_style="excited").speech_style == "bright"


def test_an_unknown_style_is_rejected_up_front():
    with pytest.raises(ValueError, match="unknown speaking style"):
        TranscriptionOptions(speech_style="furious")


def test_an_unknown_speech_model_is_rejected_up_front():
    with pytest.raises(ValueError, match="unknown speech model"):
        TranscriptionOptions(speech_model="elevenlabs")


# ----------------------------------------------------------------- the queue


def test_a_text_file_is_queued_as_a_text_source(tmp_path):
    """No stage is recorded at scan time. That was the bug."""
    source = tmp_path / "talk.txt"
    source.write_text("words", encoding="utf-8")

    store = StateStore.for_output_dir(tmp_path / "a")
    store.add_files([source])
    assert store.get(source)["mode"] == MODE_TEXT


def test_a_queue_written_by_the_old_version_still_runs(tmp_path):
    """Both legacy mode names become MODE_TEXT when the state file is read.

    Left alone they match no branch in the worker, so the file sits pending
    forever with nothing saying why - a queue that will not move and no error.
    """
    import json

    out = tmp_path / "out"
    out.mkdir()
    state = out / "transcription_state.json"
    state.write_text(
        json.dumps(
            {
                "version": 1,
                "files": {
                    "a.txt": {"path": "a.txt", "mode": "translate_text",
                              "status": "pending"},
                    "b.txt": {"path": "b.txt", "mode": "speak",
                              "status": "pending"},
                    "c.mp3": {"path": "c.mp3", "mode": "transcribe",
                              "status": "pending"},
                },
            }
        ),
        encoding="utf-8",
    )

    StateStore.for_output_dir(out)

    # Read the file back rather than going through `get`, which resolves a path
    # to an absolute key; these entries are keyed by the bare names an older
    # version happened to write.
    files = json.loads(state.read_text(encoding="utf-8"))["files"]
    assert files["a.txt"]["mode"] == MODE_TEXT
    assert files["b.txt"]["mode"] == MODE_TEXT
    # Anything that was not a text source is left exactly as it was.
    assert files["c.mp3"]["mode"] == MODE_TRANSCRIBE
    # Persisted, so the next process does not have to redo it.
    assert MODE_TRANSLATE_TEXT not in state.read_text(encoding="utf-8")


def test_a_queue_of_readings_never_loads_whisper(api, tmp_path):
    """There is no audio to decode, so downloading a decoder is pure waste."""
    source = tmp_path / "talk.txt"
    source.write_text("Read this aloud.", encoding="utf-8")
    api.manager.attach(api.output_dir)
    api.manager.store.add_files([source])

    api.manager.start(
        output_dir=api.output_dir,
        options={"speak": True, "speech_language": "en", "formats": ["srt"]},
    )
    api.wait_done()

    assert api.tertius is not None and api.tertius.warmed_up is False
    assert api.speaker is not None and api.speaker.loaded is False  # unloaded at the end
    assert api.speaker.calls
    entry = api.manager.store.get(source)
    assert entry["status"] == "done"
    assert any(p.endswith("talk.en.spoken.wav") for p in entry["outputs"])


def test_a_reading_that_changed_the_text_says_so_once(api, tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("Hello [laugh] there.", encoding="utf-8")
    api.manager.attach(api.output_dir)
    api.manager.store.add_files([source])

    api.manager.start(
        output_dir=api.output_dir,
        options={"speak": True, "speech_language": "en", "formats": ["srt"]},
    )
    api.wait_done()

    notice = api.manager.status(include_files=False)["notice"] or ""
    assert "talk.txt" in notice and "was removed" in notice


def test_a_speech_model_that_will_not_load_stops_before_anything_is_written(
    api, tmp_path
):
    source = tmp_path / "talk.txt"
    source.write_text("Read this.", encoding="utf-8")
    api.speaker_load_error = RuntimeError("no CUDA device")
    api.manager.attach(api.output_dir)
    api.manager.store.add_files([source])

    api.manager.start(
        output_dir=api.output_dir, options={"speak": True, "speech_language": "en"}
    )
    api.wait_done()

    status = api.manager.status(include_files=False)
    assert status["state"] == "error"
    assert "speaking is not available" in status["error"]
    assert api.manager.store.get(source)["status"] == "pending"


def test_preparing_a_speech_model_reports_when_it_is_ready(api):
    api.manager.prepare_speech("chatterbox-nano")
    wait_until(lambda: not api.manager.is_running(), description="prepare to finish")

    status = api.manager.status(include_files=False)
    assert status["state"] == "completed"
    assert api.speaker is not None and api.speaker.prepared
    assert "chatterbox-nano" in (status["notice"] or "")


# -------------------------------------------------------------------- the API


def test_preview_shows_what_the_tags_did_without_generating_anything(api):
    response = api.client.post(
        "/api/speech/preview",
        json={"text": "[solemn] One. [laugh] Two.", "model": MTL},
    )
    body = response.get_json()

    assert response.status_code == 200
    assert body["count"] == 1
    assert body["styles_used"] == ["solemn"]
    assert "[laugh]" not in body["chunks"][0]["text"]
    assert any("was removed" in w for w in body["warnings"])


def test_preview_reads_a_file_when_given_a_path(api, tmp_path):
    source = tmp_path / "script.txt"
    source.write_text("[urgent] Now.", encoding="utf-8")

    body = api.client.post(
        "/api/speech/preview", json={"path": str(source)}
    ).get_json()

    assert body["chunks"][0]["style"] == "urgent"
    assert body["chunks"][0]["params"]["exaggeration"] > 0.5


def test_preview_needs_something_to_read(api):
    assert api.client.post("/api/speech/preview", json={}).status_code == 400
    assert (
        api.client.post(
            "/api/speech/preview", json={"text": "hi", "model": "nope"}
        ).status_code
        == 404
    )


def test_the_language_menu_is_the_model_s_own_list(api):
    body = api.client.get(f"/api/speech/languages?model={MTL}").get_json()
    assert "en" in body["languages"] and "es" in body["languages"]
    assert "neutral" in body["styles"] and "emphatic" in body["styles"]
    assert body["aliases"]["angry"] == "urgent"
    # The multilingual model does not act on them, so it is offered none.
    assert body["paralinguistic"] == []

    turbo = api.client.get(f"/api/speech/languages?model={TURBO}").get_json()
    assert turbo["languages"] == ["en"]
    assert "laugh" in turbo["paralinguistic"]


def test_the_model_table_reports_licences_and_downloads(api):
    body = api.client.get("/api/speech/models").get_json()
    models = {entry["model"]: entry for entry in body["models"]}

    assert set(models) == {MTL, TURBO, "chatterbox-nano"}
    assert all(entry["license"] == "MIT" for entry in models.values())
    assert models[MTL]["languages"] == 23
    assert models[MTL]["download_bytes"] > 0


def test_scanning_for_speech_finds_text_files(api, tmp_path):
    folder = tmp_path / "scripts"
    folder.mkdir()
    (folder / "one.txt").write_text("a", encoding="utf-8")
    (folder / "ignored.mp3").write_bytes(b"\x00")

    body = api.client.post(
        "/api/scan", json={"directory": str(folder), "kind": "speech"}
    ).get_json()

    assert body["count"] == 1
    assert body["files"][0].endswith("one.txt")


def test_queueing_a_text_file_records_no_stage(api, tmp_path):
    """The queue says what the file *is*, never what will be done to it."""
    source = tmp_path / "one.txt"
    source.write_text("a", encoding="utf-8")
    api.manager.attach(api.output_dir)

    api.client.post("/api/queue", json={"files": [str(source)]})

    assert api.manager.store.get(source)["mode"] == MODE_TEXT


def test_the_page_renders_the_reading_controls(api):
    """The template takes new context; a typo there is a blank page, not a test."""
    page = api.client.get("/").get_data(as_text=True)

    assert page.count("opt-speak") >= 1
    for element in (
        "opt-speech-model",
        "opt-speech-language",
        "opt-speech-voice",
        "opt-speech-style",
        "btn-prepare-speech",
        "btn-browse-voice",
        "panel-speech-preview",
        "speech-table",
    ):
        assert element in page, element
    # Filled from the registry, not hand-written into the markup.
    assert "chatterbox-multilingual" in page
    assert "emphatic" in page


def test_the_srt_is_well_formed_and_matches_the_chunks(tmp_path):
    source = tmp_path / "talk.txt"
    source.write_text("First one.\n\nSecond one.", encoding="utf-8")
    out = tmp_path / "out"

    _written, result = speak_text_file(
        source, out, FakeSpeaker(), "en", formats=("srt",)
    )
    body = (out / "talk.srt").read_text(encoding="utf-8")

    assert body.startswith("1\n")
    assert "-->" in body
    for segment in result.segments:
        assert segment.text in body
    # Cues never run backwards, which is the one way an .srt is simply invalid.
    ends = [segment.end for segment in result.segments]
    starts = [segment.start for segment in result.segments]
    assert all(start < end for start, end in zip(starts, ends))
    assert starts == sorted(starts)


def test_a_reading_never_writes_over_tertius_own_files(tmp_path):
    """`transcription_state.txt` would otherwise write over the queue."""
    source = tmp_path / "transcription_state.txt"
    source.write_text("Words.", encoding="utf-8")
    out = tmp_path / "out"

    written, _result = speak_text_file(
        source, out, FakeSpeaker(), "en", formats=("json",)
    )

    names = {Path(w).name for w in written}
    assert "transcription_state.json" not in names
    assert "transcription_state.transcript.json" in names


# ------------------------------------------------- the torch that is installed


def _fake_torch(monkeypatch, *, version, cuda_available):
    """Stand in for whatever torch really is in this environment."""
    import sys
    import types

    module = types.ModuleType("torch")
    module.__version__ = version
    module.cuda = types.SimpleNamespace(is_available=lambda: cuda_available)
    monkeypatch.setitem(sys.modules, "torch", module)
    return module


def test_a_cpu_torch_in_front_of_a_gpu_is_reported(monkeypatch):
    from tertius import speech

    _fake_torch(monkeypatch, version="2.14.0+cpu", cuda_available=False)
    monkeypatch.setattr(speech, "cuda_is_present", lambda: True)

    problem = speech.torch_install_problem()
    assert problem and "2.14.0+cpu" in problem


def test_the_fix_names_this_interpreter_and_not_a_bare_pip(monkeypatch):
    """A bare `pip install` hits whatever is on PATH, which is not this venv.

    That is not hypothetical: the first version of this message said
    `pip install ...`, it was pasted into a terminal, and it installed into the
    system Python - announcing "Defaulting to user installation" while doing
    nothing at all for Tertius.
    """
    import sys

    from tertius import speech

    _fake_torch(monkeypatch, version="2.14.0+cpu", cuda_available=False)
    monkeypatch.setattr(speech, "cuda_is_present", lambda: True)

    problem = speech.torch_install_problem()
    assert sys.executable in problem
    assert "-m pip install" in problem
    # The bare form must not appear: it is the one that silently does nothing.
    assert "\n    pip install" not in problem


def test_the_fix_forces_a_reinstall(monkeypatch):
    """Without it pip changes nothing and exits 0, which reports as success.

    `torch==2.14.0+cpu` satisfies a bare `torch` requirement - the local
    version after the `+` does not make it a different version - so pip says
    "Requirement already satisfied", the GPU stays unused, and the exit code
    says it worked. That is the worst shape a failure can take, so the flag is
    pinned here.
    """
    from tertius import speech

    _fake_torch(monkeypatch, version="2.14.0+cpu", cuda_available=False)
    monkeypatch.setattr(speech, "cuda_is_present", lambda: True)

    assert "--force-reinstall" in speech.torch_install_problem()


def test_the_cuda_index_is_one_that_has_wheels_for_this_python(monkeypatch):
    """cu124 was a guess, and it carries no cp314 wheels at all.

    An index missing a wheel for the running interpreter fails with "No
    matching distribution found for torch" - which reads as though torch did
    not exist, and sends you looking in entirely the wrong place.
    """
    from tertius import speech

    assert speech.TORCH_CUDA_INDEX.endswith("/cu126")
    assert "cu124" not in speech.TORCH_CUDA_INDEX


def test_nothing_is_said_when_there_is_no_gpu_to_be_wasted(monkeypatch):
    from tertius import speech

    _fake_torch(monkeypatch, version="2.14.0+cpu", cuda_available=False)
    monkeypatch.setattr(speech, "cuda_is_present", lambda: False)
    assert speech.torch_install_problem() is None

    # And nothing when the installed torch can already see the GPU.
    _fake_torch(monkeypatch, version="2.14.0+cu126", cuda_available=True)
    monkeypatch.setattr(speech, "cuda_is_present", lambda: True)
    assert speech.torch_install_problem() is None


# ------------------------------------------------------------- the installer


class _FakePopen:
    """Stand in for pip, recording what it was asked to do."""

    calls: list[list[str]] = []

    def __init__(self, command, **kwargs):
        type(self).calls.append(list(command))
        self.stdout = iter(())

    def wait(self):
        return 0


def _capture_pip(monkeypatch):
    from tertius import speech

    _FakePopen.calls = []
    monkeypatch.setattr(speech.subprocess, "Popen", _FakePopen)
    monkeypatch.setattr(speech, "_in_a_virtualenv", lambda: True)
    return _FakePopen.calls


def _missing_once(monkeypatch, names):
    """Report `names` missing, then nothing.

    `install_requirements` asks twice - once to decide what to do, and once
    afterwards to check it worked. A stub that keeps saying "missing" makes the
    second call look like a failed install.
    """
    from tertius import speech

    answers = iter([list(names), []])

    def missing():
        try:
            return next(answers)
        except StopIteration:
            return []

    monkeypatch.setattr(speech, "missing_requirements", missing)


def test_chatterbox_is_installed_without_its_own_pins(monkeypatch):
    """`pip install chatterbox-tts` does not work, and would break translation.

    Its metadata hard-pins `spacy-pkuseg` (no cp314 wheel exists, so pip tries
    to compile it and dies without MSVC), `transformers==5.2.0` (a downgrade
    of the library the translation adapters use) and `gradio==6.8.0` (never
    imported by the library at all). All three are avoided by installing the
    real imports and then the package with `--no-deps`.
    """
    from tertius import speech

    calls = _capture_pip(monkeypatch)
    _missing_once(monkeypatch, ["chatterbox-tts"])

    speech.install_requirements()

    flat = [" ".join(call) for call in calls]
    assert any("--no-deps chatterbox-tts" in line for line in flat), flat
    # Never the bare form, which is the one that fails.
    assert not any(
        line.endswith("install chatterbox-tts") for line in flat
    ), flat
    # The real imports go in first, and the unusable pins never appear.
    deps = " ".join(flat)
    for package in ("librosa", "resemble-perth", "s3tokenizer", "conformer"):
        assert package in deps, package
    assert "spacy-pkuseg" not in deps
    assert "gradio" not in deps


def test_torch_comes_from_the_index_that_suits_the_hardware(monkeypatch):
    from tertius import speech

    calls = _capture_pip(monkeypatch)
    _missing_once(monkeypatch, ["torch"])
    monkeypatch.setattr(speech, "cuda_is_present", lambda: True)
    speech.install_requirements()
    assert any(speech.TORCH_CUDA_INDEX in " ".join(c) for c in calls), calls

    calls = _capture_pip(monkeypatch)
    _missing_once(monkeypatch, ["torch"])
    monkeypatch.setattr(speech, "cuda_is_present", lambda: False)
    speech.install_requirements()
    assert any(speech.TORCH_CPU_INDEX in " ".join(c) for c in calls), calls


def test_nothing_is_installed_outside_a_virtual_environment(monkeypatch):
    """Two and a half gigabytes into somebody's system Python, unasked."""
    from tertius import speech

    _capture_pip(monkeypatch)
    monkeypatch.setattr(speech, "_in_a_virtualenv", lambda: False)
    _missing_once(monkeypatch, ["chatterbox-tts"])

    with pytest.raises(speech.SpeechUnavailableError, match="virtual environment"):
        speech.install_requirements()
    assert _FakePopen.calls == []
