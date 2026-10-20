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
    r"(?P<chapter>\d+)\s*[:：]\s*(?P<verses>\d+(?:\s*[-–—~～,，、]\s*\d+)*)"
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
    return tuple(sorted((n for n in names if n), key=len, reverse=True))


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
