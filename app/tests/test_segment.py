"""Finding sentence ends in Arabic Whisper wrote without any.

The model itself is not loaded here; `_breaks` is replaced with a stand-in.
What it did on real readings is recorded in segment.py.
"""

from __future__ import annotations

import pytest

from tertius import segment
from tertius.segment import MIN_RUN_WORDS, restore, unpunctuated_runs
from tertius.translate import sentences_of

# 0510 as Whisper wrote it from an Arabic reading (2026-10-28): no stops.
HEARD = (
    "المن ليوم عشرة مايو أنت تضع زيتا على رأسي كأسي يفيد سفر المزامير "
    "الإصحاح ثلاثة وعشرون الآية خمسة إن امتلاء الكأس الذي يفيد له معنى مزدوج "
    "فهو كأس من الفرح وكأس من الحزن وهو يفيد من كل الجانبين ومن يريد أن يشارك "
    "في فرح الرب يجب أن يشارك أيضا في كأس معاناته علينا أن نعاني معه"
)


def _breaks_after(*ends):
    """A stand-in model: a sentence ends after each word in `ends`."""

    def breaks(words):
        return [w in ends for w in words]

    return breaks


def test_a_long_arabic_stretch_with_no_punctuation_is_found():
    words = HEARD.split()
    assert len(words) >= MIN_RUN_WORDS
    assert unpunctuated_runs(words) == [(0, len(words))]


def test_arabic_commas_count_as_punctuation():
    words = ("فهو كأس من الفرح، وكأس من الحزن، " * 8).split()
    words[-1] += "."
    assert unpunctuated_runs(words) == []


def test_words_are_kept_and_each_segment_keeps_its_own(monkeypatch):
    monkeypatch.setattr(segment, "_breaks", _breaks_after("مايو", "رأسي", "مزدوج"))
    first, second = HEARD.split(" سفر ")
    out = restore([first, "سفر " + second], "ar")

    assert out[0].startswith("المن ليوم عشرة مايو. أنت تضع زيتا على رأسي. كأسي يفيد")
    assert out[1].startswith("سفر المزامير")
    assert "له معنى مزدوج. فهو" in out[1]
    assert out[1].endswith("نعاني معه.")
    assert " ".join(out).replace(".", "").split() == HEARD.split()


def test_no_stop_inside_a_reference(monkeypatch):
    """SaT put `الآية. خمسة.` in 7 of 60 references (2026-10-29)."""
    monkeypatch.setattr(segment, "_breaks", _breaks_after("يفيد", "الآية", "خمسة"))
    [out] = restore([HEARD], "ar")

    assert "كأسي يفيد. سفر المزامير الإصحاح ثلاثة وعشرون الآية خمسة. إن" in out


def test_the_app_translates_it_as_sentences(monkeypatch):
    monkeypatch.setattr(segment, "_breaks", _breaks_after("مايو", "خمسة"))
    assert len(sentences_of([HEARD], "ar")) == 3


def test_only_arabic(monkeypatch):
    monkeypatch.setattr(segment, "_breaks", _breaks_after("مايو"))
    assert restore([HEARD], "he") == [HEARD]
    assert restore([HEARD], None) == [HEARD]


def test_without_the_model_the_text_is_unchanged(monkeypatch):
    monkeypatch.setattr(segment, "_breaks", lambda words: None)
    assert restore([HEARD], "ar") == [HEARD]


@pytest.mark.parametrize("text", ["المن ليوم 20 يناير. الرب هو مساعدي.", ""])
def test_punctuated_or_empty_text_never_reaches_the_model(monkeypatch, text):
    def refuse(words):
        raise AssertionError("the model should not have been asked")

    monkeypatch.setattr(segment, "_breaks", refuse)
    assert restore([text], "ar") == [text]
