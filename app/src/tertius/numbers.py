"""Spelling numbers out before a speech model has to read them.

Chatterbox cannot say an Arabic digit in anything but English. Measured, the
same line into three languages:

| text                        | what the audio said                        |
| --------------------------- | ------------------------------------------ |
| `Psalm 66, verses 8 and 9.` | `Psalm 66 verses 8 and 9.`      (English ✓) |
| `Салом 66, стихи 8 и 9.`    | `Салом шитая он секс, стихи от что и не.`   |
| `Salmo 66, versos 8 y 9.`   | `Salmo 15 tibesos o 39. Y no...`            |

English is fine because that is where the training data is. Everywhere else a
digit is either dropped - `Манна на 1 января` came out as `манна на января`,
the number simply gone - or turned into noise. Spelled out, the same Russian
line came back correct: `стихи восемь и девять`.

So the digits are replaced with words in the target language immediately before
the model sees the text, and nowhere else. **The cues keep the digits**: an
`.srt` reading "Псалом 66" is what a person wants to read, and
"Псалом шестьдесят шесть" is not.

`num2words` does the work. It covers 18 of the 23 languages Chatterbox speaks;
`el`, `hi`, `ms`, `sw` and `zh` raise `NotImplementedError` and their digits
are left alone, which is no worse than before.

Chinese is spelled here instead, by `_chinese`. It was once thought not to need
it, on the grounds that Chinese writes 六十六 in running text. The translator
does not: madlad writes `詩篇 66:8,9.` and `1月1日`, and Chatterbox read those
as noise. Measured on 2026-10-19, the Chinese reading of one Manna transcribed
back by Whisper, two takes each:

| text           | heard, as written              | heard, spelled out             |
| -------------- | ------------------------------ | ------------------------------ |
| `1月1日的吗哪`  | `一月七折玛娜娜`, `乐曲的曼娜`   | `1月1日的曼娜那`, `一月一日的猫娜妈` |
| `詩篇 66:8,9.`  | `诗篇6498点通`, `诗篇六小憋酒`   | `诗篇6689`, `诗篇6689`          |
"""

from __future__ import annotations

import functools
import logging
import re

log = logging.getLogger(__name__)

# Digits, and the separators that bind them into one number. `4:17` is a
# reference rather than a quantity, so each part is spoken separately - which
# is also what a person reading aloud does.
_NUMBER = re.compile(r"\d+")

# Above this, spelling a number out produces a sentence rather than a word and
# is likelier to confuse the model than the digits were. Years are the reason
# for the ceiling rather than an exception to it: "1914" wants "nineteen
# fourteen", which `num2words` does not produce, and "one thousand nine hundred
# and fourteen" is not what anybody says.
MAX_SPELLED = 9999

_CHINESE_DIGITS = "零一二三四五六七八九"
_CHINESE_PLACES = ((1000, "千"), (100, "百"), (10, "十"))


def _chinese(value: int) -> str:
    """0-9999 in Chinese numerals: 66 -> 六十六, 101 -> 一百零一, 10 -> 十.

    One 零 stands for any run of empty places inside the number, and a leading
    一十 is said as 十 - the two rules a reader would trip over.
    """
    if value < 10:
        return _CHINESE_DIGITS[value]
    out = ""
    rest = value
    for place, unit in _CHINESE_PLACES:
        count, rest = divmod(rest, place)
        if count:
            leading_ten = unit == "十" and not out and count == 1
            out += ("" if leading_ten else _CHINESE_DIGITS[count]) + unit
        elif out and rest and not out.endswith("零"):
            out += "零"
    if rest:
        out += _CHINESE_DIGITS[rest]
    return out


# Languages `num2words` cannot do, spelled here instead.
_OWN_SPELLERS = {"zh": _chinese}

# `66:8,9`, `2:10-12`: chapter, colon, then verses joined by commas and dashes.
_CHAPTER_VERSE = re.compile(
    # `.` too, after a book name only: Whisper writes "James 4.3", which was
    # read aloud as "four three three".
    r"(?P<chapter>\d+)\s*[:：.．]\s*(?P<verses>\d+(?:\s*[-–—~～,，、]\s*\d+)*)"
)
_VERSE_JOINER = re.compile(r"\s*([-–—~～,，、])\s*")
_PSALMS = ("詩篇", "诗篇")


@functools.lru_cache(maxsize=1)
def _chinese_book_names() -> tuple[str, ...]:
    """The Chinese names of the 66 books, from the table scripture.py uses.

    That table is also where the names in a translation come from - references
    are localized from it - so a reference in translated Chinese ends in one.
    """
    from .scripture import _table

    names = {
        entry.get("labels", {}).get("zh") for entry in _table().values()
    }
    names.discard(None)
    # The table is Traditional; madlad sometimes writes a book name itself,
    # in Simplified (`雅各书 4.3`). Both forms count.
    names |= {name.translate(_BOOK_T2S) for name in names}
    return tuple(sorted(names, key=len, reverse=True))


# Traditional -> Simplified for the 23 characters that differ among the 66
# Chinese book names. Generated once with OpenCC t2s, so Tertius does not need
# OpenCC to recognize a Simplified book name.
_BOOK_T2S = str.maketrans(
    "亞來傳創師彌後數書歷猶瑪紀約結羅記詩該賽門馬鴻",
    "亚来传创师弥后数书历犹玛纪约结罗记诗该赛门马鸿",
)


def _chinese_references(text: str) -> str:
    """Say `詩篇 66:8,9` the way a Chinese reader does: 詩篇第六十六篇第八、九节.

    Spelling the numbers alone was not enough. `六十六:八,九` has no word for
    the colon, Chatterbox runs the numbers together, and Whisper heard it back
    as `6689`, which madlad rendered "Chapters 66,89". Chapters of the Psalms
    are 篇 rather than 章; a range is 至 and a list is 和.

    和 and not 、 for a list, measured over four takes each: `第八、九节` was
    read without a pause and heard back as `第八九节` three times - "Psalm 66
    Chapter 89" - and `第八和第九节` was heard right all four times.

    Only after a book name, so a clock time (`10:30`) is not read as chapter
    ten, verse thirty.
    """
    books = _chinese_book_names()

    def say(match: "re.Match") -> str:
        before = text[: match.start()].rstrip()
        if not before.endswith(books):
            return match.group(0)
        unit = "篇" if before.endswith(_PSALMS) else "章"
        parts = _VERSE_JOINER.split(match.group("verses"))
        verses = "".join(
            _chinese(int(part)) if part.isdigit() else ("至" if part in "-–—~～" else "和第")
            for part in parts
        )
        return f"第{_chinese(int(match.group('chapter')))}{unit}第{verses}节"

    return _CHAPTER_VERSE.sub(say, text)


@functools.lru_cache(maxsize=1)
def _hebrew_book_names() -> tuple[str, ...]:
    """The Hebrew names of the 66 books, from the table scripture.py uses.

    With ב, כ or ל in front, `scripture.restore` writes `באיגרת` for
    `בהאיגרת`, so the two article words count without their ה as well.
    """
    from .scripture import _table

    names = {entry.get("labels", {}).get("he") for entry in _table().values()}
    names.discard(None)
    names |= {name[1:] for name in names if name.startswith(("האיגרת", "הבשורה"))}
    return tuple(sorted(names, key=len, reverse=True))


def _hebrew_masculine(value: int) -> str:
    from num2words import num2words

    return num2words(value, lang="he", gender="m")


# `ל-20 בינואר`: the day of a date, as `fixed_lines` and madlad write it.
_HEBREW_DATE = re.compile(
    r"(?<![א-ת])ל-(?P<day>\d{1,2})(?=\s+ב(?:ינואר|פברואר|מרץ|אפריל|מאי|"
    r"יוני|יולי|אוגוסט|ספטמבר|אוקטובר|נובמבר|דצמבר))"
)


def _hebrew_dates_and_references(text: str) -> str:
    """Say a date and a reference the way Google writes them out in Hebrew.

    `num2words` alone reads `ל-1 בינואר` as `ל-אחת בינואר` - the feminine
    counting form, after a hyphen - and `עברים 12:7` as `שתים עשרה:שבע`, two
    numbers with no word for the colon, the shape Chinese heard back as
    `6689` until it was said as chapter and verse.

    Asked to write them in words (2026-10-26), Google gave `מן לשלושה ביוני`
    and `לראשון ביוני` for a date - masculine, "first" as an ordinal - and
    `האיגרת אל העברים, פרק י"ב, פסוק י"א` and `תהילים, פרק ס"ו, פסוקים ח'
    ו-ט'` for references. The numbers here are masculine words, not letters:
    no measure yet says Chatterbox reads Hebrew letter numerals. A range is
    left as it was; Google kept its digits, so there is no wording to copy.
    """
    def date(match: "re.Match") -> str:
        day = int(match.group("day"))
        return "לראשון" if day == 1 else "ל" + _hebrew_masculine(day)

    text = _HEBREW_DATE.sub(date, text)
    books = _hebrew_book_names()

    def reference(match: "re.Match") -> str:
        before = text[: match.start()].rstrip()
        if not before.endswith(books):
            return match.group(0)
        parts = _VERSE_JOINER.split(match.group("verses"))
        if any(part in "-–—~～" for part in parts[1::2]):
            return match.group(0)
        verses = [int(part) for part in parts[::2]]
        chapter = _hebrew_masculine(int(match.group("chapter")))
        if len(verses) == 1:
            said = f"פסוק {_hebrew_masculine(verses[0])}"
        else:
            words = [_hebrew_masculine(v) for v in verses]
            said = "פסוקים " + " ".join(words[:-1]) + " ו" + words[-1]
        return f", פרק {chapter}, {said}"

    text = _CHAPTER_VERSE.sub(reference, text)
    # `before.rstrip()` above leaves the space between the name and the
    # reference, which now sits in front of the comma.
    return re.sub(r"\s+, פרק ", ", פרק ", text)


@functools.lru_cache(maxsize=1)
def _arabic_book_names() -> tuple[str, ...]:
    """The Arabic names of the 66 books, from the table scripture.py uses."""
    from .scripture import _table

    names = {entry.get("labels", {}).get("ar") for entry in _table().values()}
    names.discard(None)
    return tuple(sorted(names, key=len, reverse=True))


def _arabic_references(text: str) -> str:
    """Say a reference the way Google writes it out in Arabic.

    `العبرانيين 12:7` was read `اثنا عشر:سبعة`, two numbers and no word for
    the colon - the shape Chinese heard back as `6689` - and Whisper wrote it
    back as `12-7` or not at all: 24 of 60 references came back to English in
    the first Arabic run (2026-10-28). Google writes `سفر المزامير، الإصحاح
    119، الآية 105`, `الآيتان 28 و29` for two verses and `الآيات 1 و2 و3`
    for more; the digits are then spelled like any other. A range is left as
    it was, as for Hebrew.
    """
    books = _arabic_book_names()

    def reference(match: "re.Match") -> str:
        before = text[: match.start()].rstrip()
        if not before.endswith(books):
            return match.group(0)
        parts = _VERSE_JOINER.split(match.group("verses"))
        if any(part in "-–—~～" for part in parts[1::2]):
            return match.group(0)
        verses = parts[::2]
        if len(verses) == 1:
            said = f"الآية {verses[0]}"
        else:
            said = ("الآيتان " if len(verses) == 2 else "الآيات ") + " و".join(verses)
        return f"، الإصحاح {match.group('chapter')}، {said}"

    text = _CHAPTER_VERSE.sub(reference, text)
    return re.sub(r"\s+، الإصحاح ", "، الإصحاح ", text)


@functools.lru_cache(maxsize=32)
def _supported(language: str) -> bool:
    """Does `num2words` know this language? Asked once per language.

    Asked by trying it rather than by consulting a list: the advertised set and
    the working set are not the same, and the difference is five of Chatterbox's
    twenty-three.
    """
    try:
        from num2words import num2words

        num2words(1, lang=language)
        return True
    except Exception:
        return False


def spell(text: str, language: str) -> str:
    """Replace digits with words in `language`, leaving everything else alone.

    Falls back to the original text whenever anything is unavailable or
    unconvertible - a missing `num2words`, an unsupported language, a number
    too large to be worth saying. Digits that stay are no worse off than they
    were; a crash here would cost a whole reading.
    """
    if not text or not any(ch.isdigit() for ch in text):
        return text

    language = (language or "en").strip().lower()
    own = _OWN_SPELLERS.get(language)
    if own is None and not _supported(language):
        return text
    if language == "zh":
        text = _chinese_references(text)
    elif language == "he":
        text = _hebrew_dates_and_references(text)
    elif language == "ar":
        text = _arabic_references(text)

    def say(match: "re.Match") -> str:
        value = int(match.group(0))
        if value > MAX_SPELLED:
            return match.group(0)
        try:
            if own is not None:
                return own(value)
            from num2words import num2words

            return num2words(value, lang=language)
        except Exception:  # pragma: no cover - defensive
            log.debug("could not spell %s in %s", value, language, exc_info=True)
            return match.group(0)

    return _NUMBER.sub(say, text)


def would_change(text: str, language: str) -> bool:
    """Is there anything here this would actually alter?

    For the preview, which should say "these digits will be spoken as words"
    only when that is true.
    """
    return bool(text) and spell(text, language) != text
