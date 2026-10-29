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


@pytest.mark.parametrize("language", ["el", "hi", "ms", "sw"])
def test_unsupported_languages_keep_their_digits(language):
    """No worse off than before, which is the point of failing this way.

    num2words covers 18 of the 23 Chatterbox speaks.
    """
    text = "Psalm 66, verses 8 and 9."
    assert spell(text, language) == text


def test_chinese_digits_become_chinese_numerals():
    """madlad writes digits into Chinese, and Chatterbox reads them as noise.

    `詩篇 66:8,9.` was heard back as `诗篇6498点通` and `诗篇六小憋酒`;
    spelled out, as `诗篇6689` both times. num2words has no Chinese, so this
    is spelled by Tertius itself.
    """
    assert spell("1月1日的吗哪", "zh") == "一月一日的吗哪"


@pytest.mark.parametrize(
    "text, spoken",
    [
        # Psalms count in 篇, every other book in 章.
        ("詩篇 66:8,9.", "詩篇 第六十六篇第八和第九节."),
        ("帖撒羅尼迦後書 2:10-12", "帖撒羅尼迦後書 第二章第十至十二节"),
        ("約翰福音 3:16", "約翰福音 第三章第十六节"),
        ("詩篇 23:1-3, 5", "詩篇 第二十三篇第一至三和第五节"),
    ],
)
def test_a_chinese_reference_is_read_as_chapter_and_verse(text, spoken):
    """`六十六:八,九` was heard back as `6689`: the colon has no word.

    Read as 第六十六篇第八和第九节, it came back as "Psalm 66 verses 8 and 9"
    three times in four.
    """
    assert spell(text, "zh") == spoken


def test_a_clock_time_is_not_read_as_a_reference():
    """Only numbers after a book name are a chapter and verse."""
    assert spell("我们在 10:30 见面", "zh") == "我们在 十:三十 见面"


@pytest.mark.parametrize(
    "value, expected",
    [
        (0, "零"),
        (7, "七"),
        (10, "十"),
        (12, "十二"),
        (20, "二十"),
        (66, "六十六"),
        (100, "一百"),
        (101, "一百零一"),
        (110, "一百一十"),
        (1005, "一千零五"),
        (1010, "一千零一十"),
        (1914, "一千九百一十四"),
        (9999, "九千九百九十九"),
    ],
)
def test_chinese_numerals_follow_the_reading_rules(value, expected):
    """A leading 一十 is said 十, and one 零 covers any run of empty places."""
    assert spell(str(value), "zh") == expected


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
    assert would_change("Psalm 66.", "sw") is False      # unsupported
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


@pytest.mark.parametrize("text", ["雅各書 4.3", "雅各书 4.3"])
def test_a_dotted_reference_in_either_script_is_read_as_one(text):
    """Whisper writes "James 4.3"; it was read aloud as "four three three"."""
    assert spell(text, "zh").endswith("第四章第三节")


def test_a_decimal_that_follows_no_book_is_not_a_reference():
    assert spell("价格是 4.5 元", "zh") == "价格是 四.五 元"


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("מן ל-20 בינואר.", "מן לעשרים בינואר."),
        ("מן ל-3 ביוני.", "מן לשלושה ביוני."),
        # Google: "first" as an ordinal, לראשון ביוני.
        ("מן ל-1 במרץ.", "מן לראשון במרץ."),
    ],
)
def test_a_hebrew_date_is_said_as_google_writes_it(text, spoken):
    """Not `ל-אחת בינואר`, the feminine counting form after a hyphen."""
    assert spell(text, "he") == spoken


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("האיגרת אל העברים 12:7.", "האיגרת אל העברים, פרק שנים עשר, פסוק שבעה."),
        ("איגרת יעקב 4:3", "איגרת יעקב, פרק ארבעה, פסוק שלושה"),
        # A joined prefix, with the article absorbed (`scripture.restore`).
        ("באיגרת אל העברים 12:11 ועוד", "באיגרת אל העברים, פרק שנים עשר, פסוק אחד עשר ועוד"),
        ("בתהילים 66:8,9.", "בתהילים, פרק שישים ושישה, פסוקים שמונה ותשעה."),
    ],
)
def test_a_hebrew_reference_is_read_as_chapter_and_verse(text, spoken):
    """`שתים עשרה:שבע` has no word for the colon."""
    assert spell(text, "he") == spoken


def test_a_hebrew_range_and_a_clock_time_are_left_as_they_were():
    """Google kept a range's digits, so there is no wording to copy."""
    assert spell("האיגרת השנייה אל התסלוניקים 2:10-12.", "he").endswith("שתיים:עשר-שתים עשרה.")
    assert spell("בשעה 10:30 בבוקר", "he") == "בשעה עשר:שלושים בבוקר"


@pytest.mark.parametrize(
    "text, spoken",
    [
        ("الرسالة إلى العبرانيين 12:7.", "الرسالة إلى العبرانيين، الإصحاح اثنا عشر، الآية سبعة."),
        ("سفر المزامير 66:8,9.", "سفر المزامير، الإصحاح ستة و ستون، الآيتان ثمانية وتسعة."),
        ("إنجيل لوقا 1:1,2,3", "إنجيل لوقا، الإصحاح واحد، الآيات واحد واثنان وثلاثة"),
    ],
)
def test_an_arabic_reference_is_read_as_chapter_and_verse(text, spoken):
    """`اثنا عشر:سبعة` has no word for the colon."""
    assert spell(text, "ar") == spoken


def test_an_arabic_range_and_a_clock_time_are_left_as_they_were():
    assert spell("سفر المزامير 23:5-6", "ar") == "سفر المزامير ثلاثة و عشرون:خمسة-ستة"
    assert spell("الساعة 10:30 صباحا", "ar") == "الساعة عشرة:ثلاثون صباحا"
