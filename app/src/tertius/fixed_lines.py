"""Lines every Manna reading has, named from a table instead of translated.

Each Daily Heavenly Manna recording opens "Manna for <date>" and repeats its
verse after "The text again". They are the same few words in every file, and
madlad renders them worst of all: over the ten harness files (2026-10-21) the
title came back as 曼纳, 吗哪 and, twice, 放款记录 ("loan record"), and "The
text again" as 文本再次 - word for word, where Google wrote 再读一遍经文. Like a
scripture reference, a fixed line is not prose and gains nothing from a model.

Only the start of a sentence is taken. Whisper often runs the title or "The
text again" into the verse (`Manna for june 16th, no chastening, ...`,
`The text again: thou anointest my head ...`), so what follows is handed back
to be translated as usual, and the rendered words are put in front of it.

English into Chinese and Hebrew (2026-10-26), and back: Chinese into
English, for what Whisper hears of a Chinese reading (2026-10-23). There the title kept its place in 21 of 30
readings left to madlad, and in fewer once the reference beside it was
protected: with a placeholder in the sentence, madlad dropped `4月3日的玛纳`
outright. Every other pair is left to the model exactly as before.
"""

from __future__ import annotations

import re

_MONTHS = {
    name: number
    for number, name in enumerate(
        "january february march april may june july august september "
        "october november december".split(),
        start=1,
    )
}

# `Manna for January 20th.`, `Manna for may 10th`, `Manna for june 16th, no...`
_TITLE = re.compile(
    rf"^\s*Manna\s+for\s+(?P<month>{'|'.join(_MONTHS)})\s+"
    r"(?P<day>\d{1,2})(?:st|nd|rd|th)?\b\s*[.,:;!]?\s*(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)

# `The text again.`, `The text again, Rejoice...`, `The text again: thou...`.
# Punctuation or the end must follow "again", so "The text again shows that..."
# is a sentence of its own and stays one.
_AGAIN = re.compile(
    r"^\s*The\s+text\s+again\s*(?:[.,:;]\s*|$)(?P<rest>.*)$",
    re.IGNORECASE | re.DOTALL,
)

# How each line is said, per target language. `吗哪` is the Chinese Union
# Version's word for manna, and the one `speech.SPOKEN_AS` already knows how to
# have read aloud. 再读一遍经文 is Google's rendering of "The text again".
#
# Hebrew is Google's too (2026-10-26): `מן ל-20 בינואר.`, `הטקסט שוב:`.
# madlad wrote the title as `מנה` ("portion", "serving") in all ten harness
# files, and "The text again" four ways, once as invented Biblical Hebrew in
# its place (1005). The day stays a digit, as Google writes it; how it is
# said is `numbers.spell`'s business.
_TITLES = {"zh": "{month}月{day}日的吗哪", "he": "מן ל-{day} ב{month_name}"}
_AGAINS = {"zh": "再读一遍经文", "he": "הטקסט שוב"}
# The stop after a title on its own, and the colon before what follows a line.
_ALONE = {"zh": "。", "he": "."}
_BEFORE_REST = {"zh": "：", "he": ": "}
# Month names after ב: six as Google wrote them (January, March, June,
# September, October, December), six as madlad did in the harness files.
_MONTH_NAMES_BY_LANGUAGE = {
    "he": dict(enumerate(
        "ינואר פברואר מרץ אפריל מאי יוני יולי אוגוסט ספטמבר אוקטובר נובמבר דצמבר".split(),
        start=1,
    )),
}

# "The text again" opens the reading's last section, the verse read once more.
# A reading starts a new chunk there (`speech._pack`): left at the end of a
# long chunk, 0510's closing reference was cut off in four takes of four, and
# split off with its verse it was read four of four (2026-10-22).
STARTS_A_CHUNK = tuple(_AGAINS.values())

# The same two lines as Whisper writes them from a Chinese reading. Every
# spelling here is one it wrote over 60 readings (2026-10-22/23): the title as
# 玛纳 45 times, 玛娜 7, 妈哪 4, 马懒 2; 再读一遍经文 56 times and 再度一遍经文 4.
_ZH_NUMBER = r"\d{1,2}|[一二三四五六七八九十]{1,3}"
_ZH_TITLE = re.compile(
    rf"^\s*(?P<month>{_ZH_NUMBER})\s*月\s*(?P<day>{_ZH_NUMBER})\s*日的?"
    r"\s*(?:[吗玛妈马][哪纳娜懒])\s*[。.,，:：;；!！]?\s*(?P<rest>.*)$",
    re.DOTALL,
)
_ZH_AGAIN = re.compile(
    r"^\s*再[读讀度]一遍[经經]文\s*(?:[。.,，:：;；]\s*|$)(?P<rest>.*)$",
    re.DOTALL,
)
_MONTH_NAMES = {number: name.capitalize() for name, number in _MONTHS.items()}


def _zh_number(text: str) -> int:
    if text.isdigit():
        return int(text)
    digits = dict(zip("一二三四五六七八九", range(1, 10)))
    tens, _, ones = text.rpartition("十")
    if "十" not in text:
        return digits.get(text, 0)
    return (digits.get(tens, 1) if tens else 1) * 10 + digits.get(ones, 0)


def _split_chinese(text: str) -> tuple[str, str] | None:
    """`split` for a Chinese source and an English target."""
    title = _ZH_TITLE.match(text or "")
    if title:
        month, day = _zh_number(title.group("month")), _zh_number(title.group("day"))
        if not (1 <= month <= 12 and 1 <= day <= 31):
            return None
        rest = title.group("rest").strip()
        return f"Manna for {_MONTH_NAMES[month]} {day}." + (" " if rest else ""), rest
    again = _ZH_AGAIN.match(text or "")
    if not again:
        return None
    rest = again.group("rest").strip()
    return "The text again:" + (" " if rest else ""), rest


def split(
    text: str, target_language: str, source_language: str | None = "en"
) -> tuple[str, str] | None:
    """`(rendered, rest)` when `text` opens with a fixed line, else None.

    `rendered` is the fixed line in `target_language`, punctuated for what
    follows it; `rest` is the remainder of the sentence, still to translate,
    and empty when the line stood alone.
    """
    if source_language == "zh" and target_language == "en":
        return _split_chinese(text)
    if (source_language or "en") != "en" or target_language not in _TITLES:
        return None
    title = _TITLE.match(text or "")
    if title:
        day = int(title.group("day"))
        if not 1 <= day <= 31:
            return None
        month = _MONTHS[title.group("month").lower()]
        words = _TITLES[target_language].format(
            month=month,
            day=day,
            month_name=_MONTH_NAMES_BY_LANGUAGE.get(target_language, {}).get(month, ""),
        )
        rest = title.group("rest").strip()
        end = _BEFORE_REST[target_language] if rest else _ALONE[target_language]
        return words + end, rest
    again = _AGAIN.match(text or "")
    if not again:
        return None
    # Always a colon: on its own line it introduces the verse on the next.
    rest = again.group("rest").strip()
    words = _AGAINS[target_language] + _BEFORE_REST[target_language]
    return (words if rest else words.rstrip()), rest
