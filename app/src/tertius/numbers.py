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
are left alone, which is no worse than before. Chinese is the notable absence
and the notable non-problem: it writes numerals as 六十六 in running text and
handles digits itself.
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
    if not _supported(language):
        return text

    from num2words import num2words

    def say(match: "re.Match") -> str:
        value = int(match.group(0))
        if value > MAX_SPELLED:
            return match.group(0)
        try:
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
