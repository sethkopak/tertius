"""Catching text the voice model left out of a chunk.

No Whisper is loaded here; the listener is replaced where it matters. What
the real one found on real readings is recorded in listen_back.py.
"""

from __future__ import annotations

from tertius.listen_back import added_text, missing_text

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


BABBLE_SPOKEN = "黑暗的作为就是一切经不起最彻底查考的作为。让我们记起我们属于新的时代。"


def test_babble_in_the_middle_is_found():
    """0403, 2026-10-21: heard between two sentences, in none of the text."""
    heard = "黑暗的作为就是一切经不起最彻底查考的作为。这里采万,依台万,台万,采万,采万。让我们记起我们属于新的时代。"
    assert added_text(BABBLE_SPOKEN, heard) == ["这里采万依台万台万采万采万"]
    # And nothing was left out, which is why the old check passed it.
    assert missing_text(BABBLE_SPOKEN, heard) == []


def test_a_short_mishearing_is_not_babble():
    heard = BABBLE_SPOKEN.replace("查考", "查考查")
    assert added_text(BABBLE_SPOKEN, heard) == []


def test_a_word_heard_as_a_longer_one_is_not_babble():
    """One-for-one, or near it, is a mishearing either way round."""
    heard = BABBLE_SPOKEN.replace("新的时代", "新的那个时代")
    assert added_text(BABBLE_SPOKEN, heard) == []


def _speaker_with(takes, missing_by_take, added_by_take=None):
    from tertius.speech import Speaker

    calls = {"n": 0}

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            take = takes[calls["n"]]
            calls["n"] += 1
            return take

    class _Listener:
        def check(self, spoken, samples, rate, language):
            n = calls["n"] - 1
            return missing_by_take[n], (added_by_take[n] if added_by_take else [])

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


def test_a_take_that_babbled_is_generated_again():
    quiet_a, quiet_b = [0.1] * 2400 + [0.0] * 24000, [0.2] * 2400 + [0.0] * 24000
    speaker, calls = _speaker_with([quiet_a, quiet_b], [[], []], [["这里采万依台万"], []])

    assert speaker.speak(_chunk(), "zh") is quiet_b
    assert calls["n"] == 2


def test_left_out_and_added_count_together_when_choosing_a_take():
    """Seven babbled characters are worse than six left out."""
    a, b, c = ([0.1 * n] * 2400 + [0.0] * 24000 for n in (1, 2, 3))
    speaker, calls = _speaker_with(
        [a, b, c],
        [[], ["一二三四五六"], ["一二三四五六"]],
        [["七八九十一二三"], [], ["四五六七八九"]],
    )

    assert speaker.speak(_chunk(), "zh") is b
    assert calls["n"] == 3


def test_a_left_out_reference_earns_more_takes():
    """0616: three takes of three cut its Hebrews 12:11 short in one run."""
    from tertius.config import SPEECH_REFERENCE_RETRIES, SPEECH_TRUNCATION_RETRIES

    quiet = [[0.1 * n] * 2400 + [0.0] * 24000 for n in range(1, 7)]
    allowed = 1 + SPEECH_TRUNCATION_RETRIES + SPEECH_REFERENCE_RETRIES
    left_out = [["希伯來書第十二章"]] * (allowed - 1) + [[]]
    speaker, calls = _speaker_with(quiet[:allowed], left_out)

    assert speaker.speak(_chunk(), "zh") is quiet[allowed - 1]
    assert calls["n"] == allowed


def test_other_text_left_out_keeps_the_usual_budget():
    from tertius.config import SPEECH_TRUNCATION_RETRIES

    quiet = [[0.1 * n] * 2400 + [0.0] * 24000 for n in range(1, 7)]
    speaker, calls = _speaker_with(quiet, [["一二三四五六七"]] * 6)

    speaker.speak(_chunk(), "zh")
    assert calls["n"] == 1 + SPEECH_TRUNCATION_RETRIES


def test_a_reference_is_recognized_in_what_was_left_out():
    from tertius.listen_back import names_a_reference

    assert names_a_reference(["來書第十二章"])
    assert names_a_reference(["果希伯來書第十二章第十一节"])
    assert names_a_reference(["詩篇第二十三篇第五节"])
    assert not names_a_reference(["再读一遍经文"])
    assert not names_a_reference([])


REFERENCE_SPOKEN = "果希伯來書 第十二章第十一节. 正是在这样的纪律下。再读一遍经文：希伯來書 第十二章第十一节."


def test_a_chapter_too_short_to_be_a_gap_is_still_found():
    """0616, 2026-10-22: 第十二章 left out, 3 readings in 6. What `base` heard."""
    from tertius.listen_back import missing_references

    spoken = "这是由它练习: 希伯來書 第十二章第十一节."
    heard = "这是由它练习,西部来书第11节。"
    assert missing_text(spoken, heard) == []
    assert missing_references(spoken, heard) == ["第十二章"]


def test_a_reference_heard_whole_is_not_missing():
    from tertius.listen_back import missing_references

    heard = "果希伯来书第12章第11节。正是在这样的纪律下。再读一遍经文:希伯来书第十二章第十一節。"
    assert missing_references(REFERENCE_SPOKEN, heard) == []


def test_a_chapter_heard_as_the_same_sound_is_not_missing():
    """`base` on 0616: 西波兰书第12张第11节, for a reference read whole."""
    from tertius.listen_back import missing_references

    spoken = "结出了和平的义果。希伯來書 第十二章第十一节."
    assert missing_references(spoken, "结出了和平的义果,西波兰书第12张第11节。") == []
    # 0403 and 0510, the same day.
    assert missing_references("羅馬書 第十三章第十二节.", "羅馬書第13張第12節") == []
    assert missing_references("詩篇 第二十三篇第五节.", "食片第二十三片第五节") == []


def test_a_cut_reference_reaches_the_take_budget(monkeypatch):
    """Through `Listener.check`, so the extra takes see it."""
    import tertius.listen_back as L

    class _Model:
        def transcribe(self, *args, **kwargs):
            text = "这是由它练习,西部来书第11节。"
            return [type("S", (), {"text": text})()], None

    listener = L.Listener()
    listener._model = _Model()
    spoken = "这是由它练习: 希伯來書 第十二章第十一节."
    missing, added = listener.check(spoken, [0.0] * 16000, 16000, "zh")
    assert missing == ["第十二章"] and added == []
    assert L.names_a_reference(missing)


def test_other_languages_are_not_listened_to():
    from tertius.speech import Speaker

    class _Refuse:
        def check(self, *args):
            raise AssertionError("only Chinese is listened to")

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._listener = _Refuse()
    assert speaker._heard_wrong("Psalm sixty-six.", [0.0], "en") == ([], [])


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
    speaker._listener = type("L", (), {"check": lambda *a: ([], []), "unload": lambda s: None})()
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
    speaker._listener = type("L", (), {"check": lambda *a: ([], []), "unload": lambda s: None})()
    speaker.load = lambda: None
    chunk = _chunk("每日天上的吗哪。")
    speaker.speak(chunk, "zh")

    assert spoken["text"] == "每日天上的玛哪。"
    assert chunk.text == "每日天上的吗哪。"


def test_words_chatterbox_never_said_right_are_read_as_same_sound_ones():
    """白昼, 祷告, 羊羔 and the three of 2026-10-23: 1 of 24 heard right as written."""
    from tertius.speech import Speaker

    spoken = {}

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            spoken["text"] = text
            return [0.0] * 24000

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._model = _Model()
    speaker._listener = type("L", (), {"check": lambda *a: ([], []), "unload": lambda s: None})()
    speaker.load = lambda: None
    written = "白昼将临,我们学会正确的祷告,谦卑如羊羔。哀哉,渣滓无关福祉。"
    chunk = _chunk(written)
    speaker.speak(chunk, "zh")

    assert spoken["text"] == "白宙将临,我们学会正确的导告,谦卑如羊高。哀灾,渣子无关福止。"
    # The text a reader sees, and the cues, keep the real words.
    assert chunk.text == written
