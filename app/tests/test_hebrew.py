"""Adding niqqud before Hebrew is read aloud.

Nothing here downloads the model. The evidence that diacritization is needed
at all came from generating audio and transcribing it back, which costs two
model loads; that measurement is recorded in hebrew.py rather than re-run.
"""

from __future__ import annotations

import pytest

from tertius.hebrew import (
    DIACRITIZED_LANGUAGES,
    Diacritizer,
    has_hebrew,
    strip_niqqud,
)

PLAIN = "תהילים"                       # תהילים
# Built from PLAIN rather than written out, so the two cannot drift: every
# letter carries a patah, which is not real Hebrew but is exactly what
# stripping has to remove.
MARKED = "".join(ch + "ַ" for ch in PLAIN)


def test_hebrew_is_recognised_and_other_scripts_are_not():
    assert has_hebrew(PLAIN)
    assert has_hebrew("Psalm " + PLAIN)
    assert not has_hebrew("Psalm 66:8,9")
    assert not has_hebrew("")
    assert not has_hebrew("шесть")          # Cyrillic


def test_niqqud_is_stripped_back_off():
    """The model is given undiacritized text, so anything already there goes."""
    assert strip_niqqud(MARKED) == PLAIN
    assert strip_niqqud(PLAIN) == PLAIN
    assert strip_niqqud("Psalm 66") == "Psalm 66"


def test_only_hebrew_is_diacritized():
    """Every other language must not pay 635ms a chunk for nothing."""
    assert "he" in DIACRITIZED_LANGUAGES
    for code in ("en", "ru", "es", "zh", "ar"):
        assert code not in DIACRITIZED_LANGUAGES


def test_text_with_no_hebrew_never_loads_the_model():
    """A 1.2 GB download must not happen for a line that cannot need it."""
    d = Diacritizer()

    def explode():
        raise AssertionError("the model should not have been loaded")

    d.load = explode
    assert d.add_niqqud("Psalm 66:8,9") == "Psalm 66:8,9"
    assert d.add_niqqud("") == ""


def test_a_failure_speaks_the_text_rather_than_failing_the_reading():
    """Wrong vowels are a defect only a Hebrew speaker hears. No audio at all
    is a defect everyone hears, and this is not worth the second."""
    d = Diacritizer()

    def explode():
        raise RuntimeError("no network")

    d.load = explode
    assert d.add_niqqud(PLAIN) == PLAIN


def test_the_speaker_diacritizes_hebrew_and_leaves_everything_else_alone():
    """Pinned because the ordering is easy to get wrong and silent when it is.

    The digits must already be spelled out when the text reaches this, or the
    numbers are left bare and 66 is read as 60.
    """
    from tertius.speech import Speaker, SpokenChunk, style_params

    seen = []

    class _Niqqud:
        def add_niqqud(self, text):
            seen.append(text)
            return text + "!"

        def unload(self):
            pass

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            self.text = text
            return [0.0] * 10

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._model = _Model()
    speaker._diacritizer = _Niqqud()
    speaker.load = lambda: None

    chunk = SpokenChunk(
        text="תהילים 66",
        style="neutral",
        params=style_params("chatterbox-multilingual", "neutral"),
    )
    speaker.speak(chunk, "he")
    assert seen, "Hebrew should have been diacritized"
    # The digits were spelled before the diacritizer saw them.
    assert "66" not in seen[0], seen
    assert speaker._model.text.endswith("!")

    seen.clear()
    speaker.speak(SpokenChunk(text="Psalm 66", style="neutral",
                              params=chunk.params), "en")
    assert seen == [], "only Hebrew should be diacritized"
