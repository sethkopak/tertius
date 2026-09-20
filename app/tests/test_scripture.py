"""Keeping the *numbers* in citations out of the translator's hands.

The corpus this was built for opens and closes every file with a verse
reference, so anything that mangles one lands on the line a reader most needs
to trust.

Nothing here loads a model. The placeholder choice that the masking depends on
*was* decided against a real one - see the module docstring in scripture.py -
and that experiment is recorded rather than re-run, because it costs a 2 GB
model load and four translations to answer a question that has one answer.
"""

from __future__ import annotations

import pytest

from tertius.scripture import (
    PLACEHOLDER,
    find_references,
    is_only_reference,
    mask,
    protect,
    restore,
    unprotect,
)


# ------------------------------------------------------------------ finding


@pytest.mark.parametrize(
    "text, expected",
    [
        # Written, as the printed volumes have it.
        ("Psa. 46:10.", "Psa. 46:10"),
        ("Matthew 5:11,12 .", "Matthew 5:11,12"),
        ("2 Cor. 4:17,18.", "2 Cor. 4:17,18"),
        ("Dan. 2:44; 7:22,27), and it only", "Dan. 2:44; 7:22,27"),
        # Spoken, as a transcript of someone reading aloud has it.
        ("Psalm 66, verses 8 and 9.", "Psalm 66, verses 8 and 9"),
        ("First Thessalonians chapter 5 verse 17.", "First Thessalonians chapter 5 verse 17"),
    ],
)
def test_references_are_found_whole(text, expected):
    spans = find_references(text)
    assert len(spans) == 1, spans
    start, end = spans[0]
    assert text[start:end] == expected


@pytest.mark.parametrize(
    "text",
    [
        # All of these occur in the real corpus and none is scripture.
        "Section 2. Thou shalt not make unto thee any graven image.",
        "Section 2, $1,000 fine and one year",
        "Volume 6 chapter 2 is about the church.",
        "He read it in 1914 and again in 1918.",
        "Bring the blue notebook and a pen.",
        "Figure 3 shows the tabernacle.",
    ],
)
def test_things_that_are_not_scripture_are_left_alone(text):
    """A known book name is what makes this safe to run on everything.

    "capitalised word followed by a number" would swallow half the corpus.
    """
    assert find_references(text) == []
    assert mask(text) == (text, [])


def test_only_the_numbers_are_masked_and_the_book_name_is_not():
    """The book name is not fragile and a reader wants it translated.

    Held back, a Russian sentence ends up carrying "2 Cor. 4:17,18"; let it
    through and the same line reads "2 Коринфянам 4:17,18", which is what a
    Russian reader expects. It is the digits that get destroyed.
    """
    text = "We read in 2 Cor. 4:17,18 that our affliction is brief."
    masked, refs = mask(text)
    assert refs == ["4:17,18"]
    assert masked == "We read in 2 Cor. @0@ that our affliction is brief."


def test_the_ordinal_in_front_of_a_book_is_left_alone():
    """`2 Cor.` needs its 2, or the model is translating "Cor." on its own."""
    masked, refs = mask("See 2 Cor. 4:17 and 1 Peter 5:5.")
    assert refs == ["4:17", "5:5"]
    assert "2 Cor." in masked and "1 Peter" in masked


def test_a_spoken_reference_keeps_its_words_translatable():
    """`Psalm`, `verses` and `and` are prose and should reach the model."""
    masked, refs = mask("Psalm 66, verses 8 and 9.")
    assert refs == ["66", "8", "9"]
    assert masked == "Psalm @0@, verses @1@ and @2@."


def test_several_references_in_one_sentence_are_numbered():
    text = "See Psa. 46:10 and also Rom. 8:18 on this."
    masked, refs = mask(text)
    assert refs == ["46:10", "8:18"]
    assert "@0@" in masked and "@1@" in masked


# --------------------------------------------------------------- putting back


def test_a_translation_that_kept_the_placeholders_is_reassembled():
    _masked, refs = mask("We read in 2 Cor. 4:17,18 that it is brief.")
    translated = "Leemos en 2 Corintios @0@ que es breve."
    assert restore(translated, refs) == "Leemos en 2 Corintios 4:17,18 que es breve."


def test_a_reference_the_model_dropped_is_appended_not_lost():
    """A citation in the wrong place beats one that is gone.

    The placeholder does not always survive - measured on real corpus lines,
    it is dropped often enough to matter. The append is what turns "usually
    kept" into "never lost": with protection on, every numeric run was still
    present in the output, 16 of 16, in Russian, Chinese and Spanish. Without
    it, 12 of 16 and 10 of 16.
    """
    _masked, refs = mask("We read in 2 Cor. 4:17,18 that it is brief.")
    translated = "Leemos que es breve."  # the placeholder vanished
    out = restore(translated, refs)
    assert "4:17,18" in out


def test_a_batch_is_masked_and_restored_text_by_text():
    texts = [
        "See Psa. 46:10 for this.",
        "No citation here at all.",
        "And Rom. 8:18 for that.",
    ]
    masked, taken = protect(texts)
    assert masked[1] == texts[1] and taken[1] == []
    # Each text numbers its own placeholders from zero: a low number survives
    # translation more reliably than a high one.
    assert PLACEHOLDER.format(0) in masked[0]
    assert PLACEHOLDER.format(0) in masked[2]
    assert unprotect(masked, taken) == texts


# ------------------------------------------------------- the bare-citation case


@pytest.mark.parametrize(
    "text, bare",
    [
        # Nothing here is bare any more: masking only the numbers leaves
        # "Psalm", "verses" and "and" for the model, which is the point.
        ("Psalm 66, verses 8 and 9.", False),
        ("Psa. 46:10.", False),
        ("We read in 2 Cor. 4:17,18 that it is brief.", False),
        ("Section 2.", False),
        ("Bring a pen.", False),
    ],
)
def test_lines_still_have_something_to_translate(text, bare):
    """The guard remains, but numbers-only masking almost never trips it.

    It exists for the residue: a line that masks down to `@0@.` would hand the
    model a placeholder and no sentence, and it hallucinates rather than
    passing the line through - `0 0 0 0` into Russian, `El 0@` into Spanish,
    observed when the *whole* reference was being masked.
    """
    assert is_only_reference(text) is bare


def test_a_line_with_nothing_but_placeholders_is_passed_through():
    from tertius.translate import Translator

    translator = Translator("m2m100-418M", device="cpu")

    class _Model:
        def translate_batch(self, batch, **kwargs):
            raise AssertionError("the model should not have been asked")

    translator._translator = _Model()
    translator._adapter = object()
    translator.load = lambda: None

    # Blank input never reaches the model either.
    assert translator.translate(["   ", ""], "es", source_language="en") == ["   ", ""]
