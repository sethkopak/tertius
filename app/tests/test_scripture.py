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


def test_the_whole_reference_is_masked_book_name_included():
    """The book name goes with the numbers, because the model rewrites it.

    Measured, 66 books into Russian under the older numbers-only masking: 25
    came back a different book or not a book at all - Job as "Work",
    Lamentations as "Please", and five minor prophets all as "John". An
    untranslated citation is visible to a reader; a rewritten one is not.
    """
    text = "We read in 2 Cor. 4:17,18 that our affliction is brief."
    masked, refs = mask(text)
    assert refs == ["2 Cor. 4:17,18"]
    assert masked == "We read in @0@ that our affliction is brief."


def test_the_ordinal_in_front_of_a_book_travels_with_it():
    """`2 Cor.` is masked whole - the 2 is part of which book this is."""
    masked, refs = mask("See 2 Cor. 4:17 and 1 Peter 5:5.")
    assert refs == ["2 Cor. 4:17", "1 Peter 5:5"]
    assert "Cor." not in masked and "Peter" not in masked


def test_a_spoken_reference_is_taken_whole():
    """`Psalm 66, verses 8 and 9` is one citation, not a sentence with holes.

    Left partly open, the model translated "and" and left "Psalm" and "verses"
    in English - which put Latin words inside right-to-left Hebrew, and the
    reading of it audibly broke at the switch.
    """
    masked, refs = mask("Psalm 66, verses 8 and 9.")
    assert refs == ["Psalm 66, verses 8 and 9"]
    assert masked == "@0@."


def test_several_references_in_one_sentence_are_numbered():
    text = "See Psa. 46:10 and also Rom. 8:18 on this."
    masked, refs = mask(text)
    assert refs == ["Psa. 46:10", "Rom. 8:18"]
    assert masked == "See @0@ and also @1@ on this."


# --------------------------------------------------------------- putting back


def test_a_translation_that_kept_the_placeholders_is_reassembled():
    _masked, refs = mask("We read in 2 Cor. 4:17,18 that it is brief.")
    translated = "Leemos en @0@ que es breve."
    assert restore(translated, refs) == "Leemos en 2 Cor. 4:17,18 que es breve."


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
        # A whole line that is only a citation. Every file in this corpus
        # opens and closes with one, so this is the common case, not an edge.
        ("Psalm 66, verses 8 and 9.", True),
        ("Psa. 46:10.", True),
        ("We read in 2 Cor. 4:17,18 that it is brief.", False),
        ("Section 2.", False),
        ("Bring a pen.", False),
    ],
)
def test_lines_still_have_something_to_translate(text, bare):
    """A line that masks down to `@0@.` must not reach the model.

    Handed a placeholder and no sentence it invents one around it: `0 0 0 0`
    into Russian, `El 0@` into Spanish, both observed. Passing the line through
    untouched is also simply correct - there is nothing in it to translate.
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


# ------------------------------------------------- naming the book out loud


@pytest.mark.parametrize(
    "reference, book",
    [
        ("2 Cor. 4:17,18", "2 Corinthians"),
        ("Psalm 66, verses 8 and 9", "Psalms"),
        ("Psa. 46:10", "Psalms"),
        ("1 Peter 5:5", "1 Peter"),
        ("First Thessalonians chapter 5 verse 17", "1 Thessalonians"),
        ("Dan. 2:44", "Daniel"),
        # The ordinal is what tells the pair apart, and without one the
        # Gospel is meant - which is how this corpus writes it.
        ("John 3:16", "John"),
        ("1 John 2:1", "1 John"),
        ("3 John 4", "3 John"),
    ],
)
def test_a_reference_is_resolved_to_one_of_the_sixty_six(reference, book):
    from tertius.scripture import identify

    assert identify(reference) == book


def test_a_book_that_cannot_be_identified_is_not_guessed():
    """Better to leave a citation in English than to name the wrong book."""
    from tertius.scripture import identify

    assert identify("Section 2") is None
    assert identify("Volume 6 chapter 2") is None


@pytest.mark.parametrize(
    "reference, numbers",
    [
        ("Psalm 66, verses 8 and 9", "66:8,9"),
        ("2 Thessalonians 2, verses 10-12", "2:10-12"),
        ("Acts 2, verses 1 through 4", "2:1-4"),
        ("Psalm 23", "23"),
        # Already written; kept as it stands rather than re-derived.
        ("2 Cor. 4:17,18", "4:17,18"),
        ("Dan. 2:44; 7:22,27", "2:44;7:22,27"),
    ],
)
def test_a_spoken_citation_is_normalised_to_the_written_form(reference, numbers):
    """`66:8,9` needs no words, and words beside a placeholder are the defect.

    Saying "chapter" and "verse" in the target language would mean a table of
    those words too, and getting them from the model is what put English into
    the middle of a Hebrew reading in the first place.
    """
    from tertius.scripture import chapter_and_verse

    assert chapter_and_verse(reference) == numbers


def test_a_citation_is_named_in_the_target_language():
    from tertius.scripture import localize

    assert localize("Psalm 66, verses 8 and 9", "he") == "תהילים 66:8,9"
    assert localize("Psa. 46:10", "ru") == "Псалтирь 46:10"


def test_english_is_left_alone_and_an_unknown_language_falls_back():
    """The table's own English is `Book of Job`, where a citation wants `Job`.

    There is nothing to gain by rewriting a reference into the language it was
    already written in, and something to lose.
    """
    from tertius.scripture import localize

    assert localize("Job 3:16", "en") is None
    assert localize("Job 3:16", "") is None
    assert localize("Job 3:16", "xx") is None


def test_restoring_names_the_book_when_a_language_is_given():
    _masked, refs = mask("We read in Psa. 46:10 that it is so.")
    assert restore("Мы читаем в @0@, что это так.", refs, language="ru") == (
        "Мы читаем в Псалтирь 46:10, что это так."
    )
    # Without a language, exactly as before.
    assert "Psa. 46:10" in restore("... @0@ ...", refs)


def test_a_dropped_placeholder_is_appended_in_the_target_language():
    """The citation still moves to the end - but not back into English."""
    _masked, refs = mask("We read in Psa. 46:10 that it is so.")
    out = restore("Мы читаем, что это так.", refs, language="ru")
    assert "Псалтирь 46:10" in out
    assert "Psa." not in out


# ------------------------------------------------------------- the table file


def _table_file():
    import json
    from pathlib import Path

    import tertius

    path = Path(tertius.__file__).resolve().parent / "data" / "book_names.json"
    return json.loads(path.read_text(encoding="utf-8"))


def test_the_table_holds_all_sixty_six_books_with_distinct_items():
    table = _table_file()
    books = table["books"]
    assert len(books) == 66
    qids = [b["qid"] for b in books.values()]
    assert len(set(qids)) == 66, "two books pointing at one Wikidata item"
    assert "CC0" in table["source"]


def test_every_token_the_guard_knows_maps_to_a_book():
    """The guard and the table must not drift apart.

    `BOOK_NAMES` decides whether something is a citation at all; the two maps
    decide which book it is. A token in one and not the other means a reference
    that is recognised and then cannot be named, or the reverse.
    """
    from tertius.scripture import BOOK_NAMES, _TOKEN_TO_NUMBERED, _TOKEN_TO_PLAIN

    mapped = set(_TOKEN_TO_PLAIN) | set(_TOKEN_TO_NUMBERED)
    assert mapped == set(BOOK_NAMES)


def test_every_name_the_maps_produce_exists_in_the_table():
    from tertius.scripture import _NUMBERED_BOOKS, _PLAIN_BOOKS

    books = _table_file()["books"]
    names = set(_PLAIN_BOOKS)
    for base in _NUMBERED_BOOKS:
        for ordinal in (1, 2, 3):
            name = f"{ordinal} {base}"
            if name in books:
                names.add(name)
    missing = sorted(n for n in names if n not in books)
    assert not missing, f"no table entry for {missing}"


def test_the_fetcher_asks_for_the_languages_the_translator_supports():
    """A language the translator can reach but the table has never heard of
    would silently leave every citation in English for that language."""
    import sys
    from pathlib import Path

    tools = Path(__file__).resolve().parents[1] / "tools"
    sys.path.insert(0, str(tools))
    try:
        import fetch_book_names
    finally:
        sys.path.remove(str(tools))

    from tertius.translate import supported_target_languages

    assert set(fetch_book_names.LANGUAGES) == set(
        supported_target_languages("m2m100-418M")
    )
    assert len(fetch_book_names.BOOKS) == 66
