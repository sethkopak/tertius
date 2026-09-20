"""Keeping scripture references out of the translator's hands.

A reference is the one part of a verse quotation that a translation model
cannot help with and reliably destroys. Measured on a real devotional file:
`Psalm 66, verses 8 and 9.` came back from a round trip as `In the highway of
the sex poems, nonchotini, sachu.`, and the second occurrence in the same file
as `Psalm 66, verses of Father and Nev.` The corruption is in the *text* - the
model rendered the numbers as words and the words as other words - so nothing
downstream can recover it.

That matters more here than it would elsewhere. Every file in the corpus this
was built for opens and closes with a citation, so the failure lands on the
line a reader most needs to be able to trust.

The fix is not a better model, and it is not to hold the whole citation back
either. **Only the numbers are protected.**

That distinction is the whole design. The fragile part of `2 Cor. 4:17,18` is
`4:17,18` - a model asked to translate it may render the digits as words. The
book name is not fragile at all, and a reader in the target language wants it
translated: `2 Коринфянам 4:17,18` is what a Russian reader expects, where
holding the whole reference back leaves them `2 Cor. 4:17,18` in a Russian
sentence. Measured, unprotected, m2m100 gets the book name right and it is the
numbers that are at risk.

So the numeric runs inside a reference are lifted out and everything else -
"Psalm", "chapter", "verses", "and" - goes to the model as ordinary words:

    Psalm 66, verses 8 and 9   ->   Psalm @0@, verses @1@ and @2@
                               ->   Псалом @0@, стихи @1@ и @2@
                               ->   Псалом 66, стихи 8 и 9

The ordinal in front of a book is deliberately *not* masked. `2 Cor.` needs its
`2` to be recognised as Second Corinthians; replace it and the model is left
translating "Cor." on its own.

**The placeholder was chosen by experiment, not by taste.** Seven forms were
run through m2m100 into Russian, Spanish, German and Chinese:

* `⟦0⟧`, `#0#`, `xx0xx`, `|0|` and a control character were all destroyed.
* `{{0}}` survived Russian, Spanish and German - and was obliterated in
  Chinese, where the model replaced it with 《古兰经》, "the Quran".
* `@0@` survived all four, in the right order, three to a sentence.

So `@0@` it is, and the Chinese result is the reason the obvious-looking brace
form is not used. Anything that changes this should re-run that comparison
rather than reason about tokenizers.
"""

from __future__ import annotations

import logging
import re
from typing import Sequence

log = logging.getLogger(__name__)

# The placeholder. See the module docstring for why this exact shape.
PLACEHOLDER = "@{}@"
_PLACEHOLDER_RE = re.compile(r"@(\d+)@")

# Book names, including the abbreviations this corpus actually uses - taken
# from sampling it rather than from a style guide, which is why "Thes." and
# "Thess." both appear and why "Songs" is here beside "Song of Solomon".
#
# A *known book* is what makes this safe to run on everything. Matching
# "capitalised word followed by a number" would swallow "Section 2", "Figure 4"
# and "Volume 6", all of which occur in this material and none of which should
# survive translation untouched.
_BOOKS = """
genesis gen ge gn exodus exod exo ex leviticus lev le lv numbers num nu nm
deuteronomy deut deu dt joshua josh jos judges judg jdg ruth rth rut
samuel sam sa kings kgs kin chronicles chron chr ezra ezr nehemiah neh
esther esth est job jb psalms psalm psa pss ps proverbs prov pro prv
ecclesiastes eccl ecc song songs canticles isaiah isa is jeremiah jer
lamentations lam ezekiel ezek eze daniel dan dn hosea hos joel joe amos am
obadiah obad oba jonah jon micah mic nahum nah habakkuk hab zephaniah zeph
haggai hag zechariah zech zec malachi mal
matthew matt mat mt mark mrk mk luke luk lk john jhn joh jn acts act
romans rom ro corinthians cor galatians gal ephesians eph philippians phil
colossians col thessalonians thess thes tim timothy titus tit philemon phlm
hebrews heb james jas jam peter pet pe jude jud revelation rev
"""
BOOK_NAMES = frozenset(_BOOKS.split())

# Written form: `Psa. 46:10`, `2 Cor. 4:17,18`, `Dan. 2:44; 7:22,27`.
# The ordinal in front is optional and may be a numeral or a word, because a
# transcript spells out what a printed page abbreviates.
_ORDINAL = r"(?:[123]|first|second|third|1st|2nd|3rd)"
_BOOK = r"[A-Z][a-zA-Z]+"

_WRITTEN = re.compile(
    rf"\b(?:{_ORDINAL}\s+)?{_BOOK}\.?\s*"
    r"\d{1,3}"
    r"(?:\s*:\s*\d{1,3}(?:\s*[-,–]\s*\d{1,3})*)"      # 46:10, 4:17,18
    r"(?:\s*;\s*\d{1,3}\s*:\s*\d{1,3}(?:\s*[-,–]\s*\d{1,3})*)*",  # ; 7:22,27
    re.IGNORECASE,
)

# Spoken form, which is what a transcript of someone reading aloud contains:
# `Psalm 66, verses 8 and 9`, `First Thessalonians chapter 5 verse 17`.
_SPOKEN = re.compile(
    rf"\b(?:{_ORDINAL}\s+)?{_BOOK}\s*,?\s*"
    r"(?:chapter\s+)?\d{1,3}"
    r"(?:\s*,?\s*(?:verses?|vs\.?|v\.)\s*\d{1,3}"
    r"(?:\s*(?:and|through|to|-|–|,)\s*\d{1,3})*)",
    re.IGNORECASE,
)


def _names_a_book(match: "re.Match") -> bool:
    """Is the capitalised word in this match actually a book of the Bible?

    The guard that keeps "Section 2, verse 3" and "Volume 6 chapter 2" out.
    """
    words = re.findall(r"[A-Za-z]+", match.group(0))
    for word in words:
        if word.lower().rstrip(".") in BOOK_NAMES:
            return True
    return False


def find_references(text: str) -> list[tuple[int, int]]:
    """Spans in `text` that are scripture references, leftmost and longest.

    Overlaps are resolved in favour of whichever match started earlier, and
    then of the longer one - `Psalm 66, verses 8 and 9` should be taken whole
    rather than as `Psalm 66` with a stray tail.
    """
    spans: list[tuple[int, int]] = []
    for pattern in (_WRITTEN, _SPOKEN):
        for match in pattern.finditer(text or ""):
            if _names_a_book(match):
                spans.append((match.start(), match.end()))
    if not spans:
        return []

    spans.sort(key=lambda s: (s[0], -(s[1] - s[0])))
    kept: list[tuple[int, int]] = []
    for start, end in spans:
        if kept and start < kept[-1][1]:
            # Overlapping: extend the one already kept if this reaches further.
            if end > kept[-1][1]:
                kept[-1] = (kept[-1][0], end)
            continue
        kept.append((start, end))
    return kept


# A run of digits, plus the punctuation that binds digits together. `4:17,18`
# and `2:44; 7:22,27` are each one run; the comma in `Psalm 66, verses` is not,
# because what follows it is a word.
_NUMERIC_RUN = re.compile(r"\d{1,3}(?:\s*[:.,;\u2013-]\s*\d{1,3})*")


def _book_ends_at(text: str, start: int, end: int) -> int:
    """Where the book name finishes inside a reference span.

    Numbers before this point are part of the name - the `2` of `2 Cor.` - and
    must be left for the model, or it is handed "Cor." with nothing to tell it
    which one.
    """
    for word in re.finditer(r"[A-Za-z]+", text[start:end]):
        if word.group(0).lower() in BOOK_NAMES:
            return start + word.end()
    return start


def mask(text: str, offset: int = 0) -> tuple[str, list[str]]:
    """Replace the numbers inside references with placeholders.

    Returns the masked text and what was taken out, in order. Only numeric runs
    that fall inside a reference and after its book name are touched; a year,
    a page number or a section number elsewhere in the line is left alone.
    """
    spans = find_references(text)
    if not spans:
        return text, []

    cuts: list[tuple[int, int]] = []
    for start, end in spans:
        after = _book_ends_at(text, start, end)
        for run in _NUMERIC_RUN.finditer(text[after:end]):
            cuts.append((after + run.start(), after + run.end()))
    if not cuts:
        return text, []

    pieces: list[str] = []
    taken: list[str] = []
    cursor = 0
    for start, end in cuts:
        pieces.append(text[cursor:start])
        pieces.append(PLACEHOLDER.format(offset + len(taken)))
        taken.append(text[start:end])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), taken


def restore(text: str, references: Sequence[str], offset: int = 0) -> str:
    """Put the references back where the translation left their placeholders.

    A placeholder the model dropped is not silently forgiven: the reference is
    appended rather than lost, because a citation missing from a verse quotation
    is worse than one in the wrong place, and both are better than the model's
    own rendering of it.
    """
    if not references:
        return text

    seen: set[int] = set()

    def put_back(match: "re.Match") -> str:
        index = int(match.group(1)) - offset
        if 0 <= index < len(references):
            seen.add(index)
            return references[index]
        return match.group(0)

    out = _PLACEHOLDER_RE.sub(put_back, text)

    missing = [ref for i, ref in enumerate(references) if i not in seen]
    if missing:
        log.warning(
            "the translation dropped %d reference placeholder(s); appending: %s",
            len(missing),
            "; ".join(missing),
        )
        out = out.rstrip()
        joiner = " " if out and not out.endswith((".", "!", "?")) else " "
        out = f"{out}{joiner}{' '.join(missing)}"
    return out


def is_only_reference(text: str) -> bool:
    """Is there nothing here for the model but placeholders and punctuation?

    Kept, but it almost never fires now that only the numbers are masked.
    `Psalm 66, verses 8 and 9.` still has "Psalm", "verses" and "and" in it and
    *should* be translated, which is the point of protecting numbers rather
    than citations. This catches the residue - a line that masks down to
    `@0@.` and would leave the model a placeholder and no sentence, which makes
    it hallucinate rather than pass the line through.
    """
    masked, refs = mask(text or "")
    if not refs:
        return False
    left = _PLACEHOLDER_RE.sub("", masked)
    return not any(ch.isalnum() for ch in left)


def protect(texts: Sequence[str]) -> tuple[list[str], list[list[str]]]:
    """Mask a batch. Each text is numbered from zero in its own right.

    Per text rather than across the batch, because the model sees one text at a
    time and a low number is likelier to survive than a high one.
    """
    masked: list[str] = []
    taken: list[list[str]] = []
    for text in texts:
        one, refs = mask(text or "")
        masked.append(one)
        taken.append(refs)
    return masked, taken


def unprotect(texts: Sequence[str], taken: Sequence[Sequence[str]]) -> list[str]:
    """Undo `protect`, text by text."""
    return [
        restore(text, refs) if refs else text
        for text, refs in zip(texts, taken)
    ]
