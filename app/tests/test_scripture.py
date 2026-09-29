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
    keep_final_stop,
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


# ------------------------------------------------ the stop after a last citation
#
# Seen on the hosted m2m100 on 2026-09-29, in Russian, Spanish and Hebrew: a
# sentence ending on a citation came back with its full stop gone.


def test_a_stop_dropped_after_the_last_citation_is_put_back():
    masked, refs = mask("Compare Job 3:16 with Lamentations 3:22.")
    assert masked == "Compare @0@ with @1@."
    # What the model actually returned, word for word.
    [out] = unprotect(["Сравнить @0@ с @1@"], [refs], "ru", sources=[masked])
    assert out == "Сравнить Книгу Иова 3:16 с Плачем Иеремии 3:22."


def test_a_stop_the_model_kept_is_not_doubled():
    masked, refs = mask("Compare Job 3:16 with Lamentations 3:22.")
    [out] = unprotect(["Compare @0@ con @1@."], [refs], "es", sources=[masked])
    assert out.endswith("3:22.") and not out.endswith("..")


@pytest.mark.parametrize(
    "language, source_end, expected_end",
    [
        ("zh", ".", "。"),
        ("ja", "?", "？"),
        ("hi", ".", "।"),
        ("ar", "?", "؟"),
        ("ru", "!", "!"),
        ("es", "?", "?"),
    ],
)
def test_the_stop_put_back_is_the_target_languages_own(language, source_end, expected_end):
    source = f"Compare @0@ with @1@{source_end}"
    assert keep_final_stop(source, "X @0@ Y @1@", language).endswith(expected_end)


def test_a_rephrased_ending_is_left_alone():
    """The model moved the citation and ended the sentence its own way.

    That is a choice, not a dropped stop, and guessing a stop onto it could put
    a period in the middle of a sentence that merely lacks one at the end."""
    source = "Compare @0@ with @1@."
    assert keep_final_stop(source, "Compare @1@ and @0@ closely", "en") == "Compare @1@ and @0@ closely"


def test_a_source_that_does_not_end_on_a_citation_is_left_alone():
    source = "See @0@ for this."
    assert keep_final_stop(source, "Voir @0@", "fr") == "Voir @0@"


def test_a_closing_quote_after_the_stop_does_not_stop_the_repair():
    source = "He said, “Read @0@.”"
    assert keep_final_stop(source, "Il a dit : « Lisez @0@", "fr") == "Il a dit : « Lisez @0@."


# ------------------------------------------------- Hebrew's attached prefixes
#
# Seen on the hosted m2m100 on 2026-09-29: `in @0@` came back `ב @0@`, which put
# back read `ב תהילים` where Hebrew writes `בתהילים`.


def _he(sentence: str, masked_translation: str) -> str:
    _masked, refs = mask(sentence)
    return restore(masked_translation, refs, language="he")


def test_a_detached_hebrew_prefix_is_joined_to_the_book():
    # The model's own output, word for word.
    out = _he(
        "As we read in Psalm 66:8, 9, the Lord holds our soul in life.",
        "כפי שאנחנו קוראים ב @0@, האדון שומר על הנשמה שלנו בחיים.",
    )
    assert "קוראים בתהילים 66:8,9," in out


def test_and_is_joined_too_and_so_is_and_in():
    out = _he("Compare Job 3:16 with Lamentations 3:22.", "השוואת @0@ עם @1@ ו @0@.")
    assert "ו" + "ספר איוב" in out
    out = _he("Read Romans 8:28.", "קרא וב @0@.")
    assert "ובאיגרת אל הרומאים 8:28" in out


def test_in_to_and_as_absorb_the_article():
    # "in the Epistle to the Romans" - the ה goes.
    assert "באיגרת אל הרומאים" in _he("See Romans 8:28.", "ראה ב @0@.")
    assert "לבשורה על-פי מתי" in _he("Turn to Matthew 5:3.", "פנה ל @0@.")
    # "from" does not absorb it.
    assert "מהאיגרת אל הרומאים" in _he("From Romans 8:28.", "מ @0@.")


def test_hosea_keeps_the_he_that_is_part_of_its_name():
    """A leading ה is not always the article. Dropping it here writes `בושע`."""
    assert "בהושע 6:6" in _he("As in Hosea 6:6.", "כמו ב @0@.")


def test_words_that_begin_with_prefix_letters_are_left_alone():
    # `של` is "of" and `מה` is "what"; neither is a prefix to be joined.
    out = _he("The words of Psalm 23:1.", "המילים של @0@.")
    assert "של תהילים 23:1" in out


def test_a_prefix_on_a_name_left_in_english_takes_a_hyphen():
    from tertius.scripture import _after_hebrew_prefix

    assert _after_hebrew_prefix("קוראים ב", "Psalm 66:8") == "-Psalm 66:8"


def test_other_languages_are_not_touched_by_the_hebrew_rule():
    _masked, refs = mask("See Romans 8:28.")
    assert restore("Mira b @0@.", refs, language="es").startswith("Mira b ")


# ------------------------------------------------ Russian cases after prepositions
#
# Seen on the hosted m2m100 on 2026-09-29: `in @0@` came back `в @0@`, which put
# back read `в Псалтирь` - the table's nominative where Russian needs `в Псалтири`.


def _ru(sentence: str, masked_translation: str) -> str:
    _masked, refs = mask(sentence)
    return restore(masked_translation, refs, language="ru")


def test_in_takes_the_prepositional():
    # The model's own output, word for word.
    out = _ru(
        "As we read in Psalm 66:8, 9, the Lord holds our soul in life.",
        "Как мы читаем в @0@, Господь держит нашу душу в живых.",
    )
    assert "читаем в Псалтири 66:8,9," in out


@pytest.mark.parametrize(
    "sentence, masked, expected",
    [
        # Only the head noun declines; the fixed part after it does not.
        ("In Job 3:16.", "В @0@.", "В Книге Иова 3:16."),
        ("In Romans 8:28.", "В @0@.", "В Послании к Римлянам 8:28."),
        ("From Matthew 5:3.", "Из @0@.", "Из Евангелия от Матфея 5:3."),
        ("To Romans 8:28.", "К @0@.", "К Посланию к Римлянам 8:28."),
        ("With Lamentations 3:22.", "С @0@.", "С Плачем Иеремии 3:22."),
        ("In Revelation 1:1.", "В @0@.", "В Откровении Иоанна Богослова 1:1."),
        ("In Acts 2:4.", "В @0@.", "В Деяниях святых апостолов 2:4."),
        ("In Ruth 1:16.", "В @0@.", "В Книге Руфь 1:16."),
        # An ordinal declines with its noun.
        ("In 1 Kings 3:5.", "В @0@.", "В Третьей книге Царств 3:5."),
        ("In 1 Corinthians 13:4.", "В @0@.", "В 1-м послании к Коринфянам 13:4."),
        ("From 1 Corinthians 13:4.", "Из @0@.", "Из 1-го послания к Коринфянам 13:4."),
        ("In 1 Chronicles 16:34.", "В @0@.", "В 1-й Паралипоменон 16:34."),
    ],
)
def test_the_book_takes_the_case_its_preposition_governs(sentence, masked, expected):
    assert _ru(sentence, masked) == expected


@pytest.mark.parametrize(
    "sentence, masked, expected",
    [
        # What the hosted model wrote before a citation, word for word
        # (probed 2026-09-29). All take the accusative.
        ("Compare Job 3:16 with Lamentations 3:22.", "Сравнить @0@ с @1@.",
         "Сравнить Книгу Иова 3:16 с Плачем Иеремии 3:22."),
        ("Read Romans 8:28 carefully.", "Читайте @0@ внимательно.",
         "Читайте Послание к Римлянам 8:28 внимательно."),
        ("Consider Hebrews 11:1.", "Рассмотрим @0@ на мгновение.",
         "Рассмотрим Послание к Евреям 11:1 на мгновение."),
        ("Paul quotes Psalm 16:10.", "Пол цитирует @0@ здесь.",
         "Пол цитирует Псалтирь 16:10 здесь."),
        ("Remember Job 19:25.", "Помните @0@.", "Помните Книгу Иова 19:25."),
        ("Study 1 Kings 3:5.", "Мы будем изучать @0@.",
         "Мы будем изучать Третью книгу Царств 3:5."),
    ],
)
def test_a_verb_that_takes_an_object_puts_the_book_in_the_accusative(sentence, masked, expected):
    assert _ru(sentence, masked) == expected


@pytest.mark.parametrize(
    "masked",
    [
        # The book as subject: nominative is right.
        "@0@ говорит нам почему.",
        "Это @0@.",
        # A verbal noun from the same stem wants the genitive, not the
        # accusative; left alone rather than put in the wrong case.
        "Изучение @0@ полезно.",
        # Reflexive: no object at all.
        "Это сравнивается @0@.",
        # `равно` is not "compare".
        "Равно @0@.",
    ],
)
def test_a_name_after_anything_else_stays_nominative(masked):
    assert "Книга Иова 3:16" in _ru("Job 3:16.", masked)


def test_an_ambiguous_preposition_is_left_alone():
    # `на` is location or direction; a wrong case is no better than none.
    assert "на Послание к Римлянам" in _ru("Look at Romans 8:28.", "Посмотрите на @0@.")


def test_other_languages_are_not_declined():
    _masked, refs = mask("In Psalm 23:1.")
    assert "Salmos" in restore("En @0@.", refs, language="es")


def test_without_sources_unprotect_behaves_exactly_as_before():
    masked, refs = mask("Compare Job 3:16 with Lamentations 3:22.")
    [out] = unprotect(["Сравнить @0@ с @1@"], [refs], "ru")
    assert out == "Сравнить Книгу Иова 3:16 с Плачем Иеремии 3:22"


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
    # `в Псалтири`, prepositional after `в` - this said `в Псалтирь` until the
    # case was fixed on 2026-09-29, pinning the bug as the expected answer.
    assert restore("Мы читаем в @0@, что это так.", refs, language="ru") == (
        "Мы читаем в Псалтири 46:10, что это так."
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

    assert len(fetch_book_names.BOOKS) == 66

    # The translator's list is read from the converted model's vocabulary, and
    # is empty until a model has been converted - which it never has been on a
    # CI runner. Compared against that empty set this failed on every platform
    # from 2026-09-21 while passing on the one machine with a model on it.
    supported = supported_target_languages("m2m100-418M")
    if not supported:
        pytest.skip("m2m100-418M is not converted here, so it has no language list")
    assert set(fetch_book_names.LANGUAGES) == set(supported)
