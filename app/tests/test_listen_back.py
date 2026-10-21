"""Catching text the voice model left out of a chunk.

No Whisper is loaded here; the listener is replaced where it matters. What
the real one found on real readings is recorded in listen_back.py.
"""

from __future__ import annotations

from tertius.listen_back import missing_text

SPOKEN = "经文又说,你们要思想那忍受罪人这样反对他的,恐怕你们心里疲乏乏力。希伯來書 第十二章第三节."


def test_a_reference_left_off_the_end_is_found():
    """1005: the reading stopped after the quotation, before its reference."""
    heard = "经文又说,你们要思想那忍受罪人这样反对他的,恐怕你们心里疲乏乏力。"
    assert missing_text(SPOKEN, heard) == ["希伯來書第十二章第三节"]


def test_simplified_characters_and_digits_heard_back_are_not_omissions():
    heard = "经文又说你们要思想那忍受罪人这样反对他的恐怕你们心里疲乏乏力希伯来书第12章第3节"
    assert missing_text(SPOKEN, heard) == []


def test_a_short_mishearing_is_not_an_omission():
    heard = SPOKEN.replace("疲乏乏力", "皮发")
    assert missing_text(SPOKEN, heard) == []


def _speaker_with(takes, missing_by_take):
    from tertius.speech import Speaker

    calls = {"n": 0}

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            take = takes[calls["n"]]
            calls["n"] += 1
            return take

    class _Listener:
        def missing(self, spoken, samples, rate, language):
            return missing_by_take[calls["n"] - 1]

        def unload(self):
            pass

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._model = _Model()
    speaker._listener = _Listener()
    speaker.load = lambda: None
    return speaker, calls


def _chunk(text="你们要思想那忍受罪人这样反对他的。"):
    from tertius.speech import SpokenChunk, style_params

    return SpokenChunk(text, "neutral", style_params("chatterbox-multilingual", "neutral"))


def test_a_take_that_left_text_out_is_generated_again():
    # Quiet endings, so only the listener can be asking for the retry.
    incomplete, complete = [0.1] * 2400 + [0.0] * 24000, [0.2] * 2400 + [0.0] * 24000
    speaker, calls = _speaker_with([incomplete, complete], [["希伯來書第十二章"], []])

    assert speaker.speak(_chunk(), "zh") is complete
    assert calls["n"] == 2


def test_the_most_complete_take_is_kept_when_none_is_whole():
    a, b, c = ([0.1 * n] * 2400 + [0.0] * 24000 for n in (1, 2, 3))
    speaker, calls = _speaker_with([a, b, c], [["一二三四五六七八"], ["一二三四五六"], ["一二三四五六七"]])

    assert speaker.speak(_chunk(), "zh") is b
    assert calls["n"] == 3


def test_other_languages_are_not_listened_to():
    from tertius.speech import Speaker

    class _Refuse:
        def missing(self, *args):
            raise AssertionError("only Chinese is listened to")

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._listener = _Refuse()
    assert speaker._left_out("Psalm sixty-six.", [0.0], "en") == []


def test_quotation_marks_are_not_read_into_chinese():
    """Chatterbox stopped at `。 "` and never read the reference after it."""
    from tertius.speech import Speaker

    spoken = {}

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            spoken["text"] = text
            return [0.0] * 24000

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._model = _Model()
    speaker._listener = type("L", (), {"missing": lambda *a: [], "unload": lambda s: None})()
    speaker.load = lambda: None
    speaker.speak(_chunk('经文又说 : " 你们要思想 。 " 希伯來書 12:3.'), "zh")

    assert '"' not in spoken["text"]
    assert spoken["text"].endswith("希伯來書 第十二章第三节.")


def test_manna_is_read_with_the_spelling_the_model_says_right():
    """吗哪 was heard as 妈 ("mother") two takes in four; 玛哪 never."""
    from tertius.speech import Speaker

    spoken = {}

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            spoken["text"] = text
            return [0.0] * 24000

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._model = _Model()
    speaker._listener = type("L", (), {"missing": lambda *a: [], "unload": lambda s: None})()
    speaker.load = lambda: None
    chunk = _chunk("每日天上的吗哪。")
    speaker.speak(chunk, "zh")

    assert spoken["text"] == "每日天上的玛哪。"
    assert chunk.text == "每日天上的吗哪。"
