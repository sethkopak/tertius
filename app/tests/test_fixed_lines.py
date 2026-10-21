"""The lines every Manna reading has, named from a table instead of translated.

See src/tertius/fixed_lines.py. The sentences here are the ten harness files'
own, as the translator received them on 2026-10-21.
"""

from __future__ import annotations

import pytest

from tertius.fixed_lines import split


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Manna for January 20th.", ("1月20日的吗哪。", "")),
        ("Manna for April 3rd.", ("4月3日的吗哪。", "")),
        # Whisper does not always capitalize the month.
        ("Manna for may 10th.", ("5月10日的吗哪。", "")),
        ("Manna for December 18th.", ("12月18日的吗哪。", "")),
        # Run into the verse: the verse is still the model's to translate.
        (
            "Manna for june 16th, no chastening, for the present seemeth to be joyous but grievous.",
            ("6月16日的吗哪：", "no chastening, for the present seemeth to be joyous but grievous."),
        ),
    ],
)
def test_the_title_is_named_from_the_date(text, expected):
    """madlad wrote this line three ways in ten files, twice as "loan record"."""
    assert split(text, "zh") == expected


@pytest.mark.parametrize(
    "text, rest",
    [
        ("The text again.", ""),
        ("The text again", ""),
        (
            "The text again, Rejoice in the Lord always, and again I say rejoice.",
            "Rejoice in the Lord always, and again I say rejoice.",
        ),
        (
            "The text again: thou anointest my head with oil, my cup runneth over.",
            "thou anointest my head with oil, my cup runneth over.",
        ),
        (
            "The text again. giving all diligence, add to your faith virtue or fortitude.",
            "giving all diligence, add to your faith virtue or fortitude.",
        ),
    ],
)
def test_the_text_again_introduces_the_verse(text, rest):
    """Always with a colon: on a line of its own the verse is on the next."""
    assert split(text, "zh") == ("再读一遍经文：", rest)


@pytest.mark.parametrize(
    "text",
    [
        # "again" followed by a verb is a sentence, not the fixed line.
        "The text again shows that he is faithful.",
        "Manna for the hungry soul is his word.",
        "Manna for Smarch 3rd.",
        "Manna for June 45th.",
        "We read the text again.",
        "If ye endure chastening, God dealeth with you as with sons.",
    ],
)
def test_other_sentences_are_left_to_the_model(text):
    assert split(text, "zh") is None


def test_only_english_into_chinese_for_now():
    """The only pair this was measured on. Everything else is unchanged."""
    assert split("Manna for January 20th.", "es") is None
    assert split("The text again.", "ru") is None
    assert split("Manna for January 20th.", "zh", source_language="de") is None
    # No source given means English, as in `Translator.translate`.
    assert split("The text again.", "zh", source_language=None) is not None
