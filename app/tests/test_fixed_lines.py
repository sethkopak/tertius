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


@pytest.mark.parametrize(
    "heard, expected",
    [
        ("1月20日的玛娜。", ("Manna for January 20.", "")),
        ("十月五日的玛纳", ("Manna for October 5.", "")),
        ("8月29日的妈哪,你们求也得不着", ("Manna for August 29. ", "你们求也得不着")),
        ("5月10日的马懒,你用油膏我的头", ("Manna for May 10. ", "你用油膏我的头")),
        ("再读一遍经文。", ("The text again:", "")),
        ("再度一遍经文,你们要靠主常常喜乐", ("The text again: ", "你们要靠主常常喜乐")),
    ],
)
def test_the_lines_come_back_into_english(heard, expected):
    """As Whisper wrote them from a Chinese reading, 2026-10-22/23."""
    assert split(heard, "en", source_language="zh") == expected


@pytest.mark.parametrize(
    "heard",
    ["13月5日的玛纳", "我们要再读一遍经文吗", "黑暗的作为就是一切经不起最彻底查考的作为"],
)
def test_other_chinese_is_left_to_the_model(heard):
    assert split(heard, "en", source_language="zh") is None


def test_only_the_pairs_measured():
    """English into Chinese and back. Everything else is unchanged."""
    assert split("1月20日的玛娜。", "es", source_language="zh") is None
    assert split("Manna for January 20th.", "es") is None
    assert split("The text again.", "ru") is None
    assert split("Manna for January 20th.", "zh", source_language="de") is None
    # No source given means English, as in `Translator.translate`.
    assert split("The text again.", "zh", source_language=None) is not None


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Manna for January 20th.", ("מן ל-20 בינואר.", "")),
        ("Manna for October 5th.", ("מן ל-5 באוקטובר.", "")),
        (
            "Manna for june 16th, no chastening, for the present seemeth to be joyous but grievous.",
            ("מן ל-16 ביוני: ", "no chastening, for the present seemeth to be joyous but grievous."),
        ),
        ("The text again.", ("הטקסט שוב:", "")),
        (
            "The text again, Consider him who endured such contradiction of sinners against himself.",
            ("הטקסט שוב: ", "Consider him who endured such contradiction of sinners against himself."),
        ),
    ],
)
def test_the_hebrew_lines_are_googles(text, expected):
    """madlad wrote `מנה` ("portion") for the title in all ten harness files,
    and in 1005 put invented Biblical Hebrew where "The text again" was."""
    assert split(text, "he") == expected


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Manna for January 20th.", ("المنّ ليوم 20 يناير.", "")),
        ("Manna for August 5th.", ("المنّ ليوم 5 أغسطس.", "")),
        ("The text again.", ("النص مجددًا:", "")),
        # Whisper's `Text again.` too.
        ("Text again.", ("النص مجددًا:", "")),
        # madlad: "the Riyadh daily newspaper".
        ("Daily Heavenly Manna.", ("المنّ السماوي اليومي.", "")),
        ("Daily Heavenly Manna. Manna for January 1st.", ("المنّ السماوي اليومي. المنّ ليوم 1 يناير.", "")),
        (
            "The text again, Consider him who endured such contradiction of sinners against himself.",
            ("النص مجددًا: ", "Consider him who endured such contradiction of sinners against himself."),
        ),
    ],
)
def test_the_arabic_lines_are_googles(text, expected):
    """madlad wrote `منّا` for the title, and with "The text again," in front
    of 1005's verse rendered it as a Qur'an verse (2026-10-28)."""
    assert split(text, "ar") == expected
