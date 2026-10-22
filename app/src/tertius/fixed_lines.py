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

English into Chinese only, for now: those are the readings this was measured
on. Every other pair is left to the model exactly as before.
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
_TITLES = {"zh": "{month}月{day}日的吗哪"}
_AGAINS = {"zh": "再读一遍经文"}
# The stop after a title on its own, and the colon before what follows a line.
_ALONE = {"zh": "。"}
_BEFORE_REST = {"zh": "："}

# "The text again" opens the reading's last section, the verse read once more.
# A reading starts a new chunk there (`speech._pack`): left at the end of a
# long chunk, 0510's closing reference was cut off in four takes of four, and
# split off with its verse it was read four of four (2026-10-22).
STARTS_A_CHUNK = tuple(_AGAINS.values())


def split(
    text: str, target_language: str, source_language: str | None = "en"
) -> tuple[str, str] | None:
    """`(rendered, rest)` when `text` opens with a fixed line, else None.

    `rendered` is the fixed line in `target_language`, punctuated for what
    follows it; `rest` is the remainder of the sentence, still to translate,
    and empty when the line stood alone.
    """
    if (source_language or "en") != "en" or target_language not in _TITLES:
        return None
    title = _TITLE.match(text or "")
    if title:
        day = int(title.group("day"))
        if not 1 <= day <= 31:
            return None
        words = _TITLES[target_language].format(
            month=_MONTHS[title.group("month").lower()], day=day
        )
        rest = title.group("rest").strip()
        end = _BEFORE_REST[target_language] if rest else _ALONE[target_language]
        return words + end, rest
    again = _AGAIN.match(text or "")
    if not again:
        return None
    # Always a colon: on its own line it introduces the verse on the next.
    return _AGAINS[target_language] + _BEFORE_REST[target_language], again.group("rest").strip()
