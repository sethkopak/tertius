"""Spelling digits out before the voice model has to read them.

Chatterbox can only say an Arabic digit in English. Everywhere else it drops
the number or makes noise - `Манна на 1 января` came out as `манна на января`,
the digit simply gone, and `Salmo 66, versos 8 y 9` as `Salmo 15 tibesos o 39`.

Nothing here loads a voice model. That the spelled-out form is what fixes it
was established against a real one and is recorded in the module docstring.
"""

from __future__ import annotations

import pytest

from tertius.numbers import MAX_SPELLED, spell, would_change

# `num2words` is optional - it belongs to the speak extra, not the base
# install. Without it `spell` correctly returns the text unchanged, so every
# assertion here would fail as though the feature were broken rather than
# absent. An explicit skip rather than `importorskip`, which is documented
# around a module being missing and not around one that refuses to load.
try:  # noqa: SIM105 - the import is the test
    import num2words as _num2words  # noqa: F401
except Exception:  # pragma: no cover - only when the extra is not installed
    pytest.skip(
        "num2words is part of the speak extra", allow_module_level=True
    )


RU_SIXTY_SIX = "шестьдесят шесть"


def test_digits_become_words_in_the_target_language():
    assert spell("Psalm 66.", "en") == "Psalm sixty-six."
    assert spell("Salmo 66.", "es") == "Salmo sesenta y seis."
    assert RU_SIXTY_SIX in spell("Псалом 66.", "ru")


def test_every_number_in_a_line_is_spoken():
    out = spell("Psalm 66, verses 8 and 9.", "en")
    assert out == "Psalm sixty-six, verses eight and nine."


def test_a_reference_is_spoken_part_by_part():
    """`4:17` is a pointer, not a quantity.

    Each part is said separately, which is what a person reading aloud does -
    "four seventeen", not "four hundred and seventeen".
    """
    assert spell("2 Cor. 4:17", "en") == "two Cor. four:seventeen"


@pytest.mark.parametrize("language", ["el", "hi", "ms", "sw", "zh"])
def test_unsupported_languages_keep_their_digits(language):
    """No worse off than before, which is the point of failing this way.

    num2words covers 18 of the 23 Chatterbox speaks. Chinese is the notable
    absence and the notable non-problem: it writes numerals in running text and
    handles digits itself.
    """
    text = "Psalm 66, verses 8 and 9."
    assert spell(text, language) == text


def test_text_without_digits_is_returned_untouched():
    text = "O bless our God, ye people."
    assert spell(text, "ru") is text


def test_a_number_too_large_to_say_is_left_alone():
    """Spelling a big number out produces a sentence, not a word.

    Years are the reason for the ceiling rather than an exception to it: 1914
    wants "nineteen fourteen", which num2words does not produce, and "one
    thousand nine hundred and fourteen" is not what anybody says.
    """
    big = str(MAX_SPELLED + 1)
    assert big in spell(f"It cost {big} pounds.", "en")


def test_an_unknown_language_falls_back_rather_than_raising():
    """A crash here would cost a whole reading; digits only cost a number."""
    text = "Psalm 66."
    assert spell(text, "xx") == text
    assert spell(text, "zz-ZZ") == text


def test_no_language_at_all_means_english():
    """The same fallback the rest of the app uses, not a refusal to act.

    Nothing calls it this way - `Speaker.speak` always has a resolved language -
    but defaulting somewhere else than the rest of the code would be its own
    small trap.
    """
    assert spell("Psalm 66.", "") == "Psalm sixty-six."
    assert spell("Psalm 66.", None) == "Psalm sixty-six."


def test_would_change_only_reports_a_real_difference():
    assert would_change("Psalm 66.", "en") is True
    assert would_change("Psalm 66.", "zh") is False      # unsupported
    assert would_change("O bless our God.", "en") is False


def test_the_speaker_spells_but_the_cue_keeps_the_digits():
    """The `.srt` should read "Псалом 66"; only the model gets the words."""
    from tertius.speech import SpokenChunk, Speaker, style_params

    spoken = {}

    class _Model:
        sr = 24000

        def generate(self, text, **kwargs):
            spoken["text"] = text
            return [0.0] * 10

    speaker = Speaker("chatterbox-multilingual", device="cpu")
    speaker._model = _Model()
    speaker.load = lambda: None

    chunk = SpokenChunk(
        text="Psalm 66, verses 8 and 9.",
        style="neutral",
        params=style_params("chatterbox-multilingual", "neutral"),
    )
    speaker.speak(chunk, "en")

    assert spoken["text"] == "Psalm sixty-six, verses eight and nine."
    # The chunk itself is untouched, so the cues still carry the digits.
    assert chunk.text == "Psalm 66, verses 8 and 9."
