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

The fix is not a better model. **The whole reference is protected**, book name
and numbers together:

    We read in 2 Cor. 4:17,18 that our affliction is brief.
    ->  We read in @0@ that our affliction is brief.
    ->  Мы читаем в @0@, что наша скорбь кратковременна.
    ->  Мы читаем в 2 Cor. 4:17,18, что наша скорбь кратковременна.

This reverses the original design, which held back only the numeric runs and
let "Psalm", "chapter", "verses" and the book name go to the model as ordinary
words. That rested on a claim - "m2m100 gets the book name right and it is the
numbers that are at risk" - which was asserted rather than measured. Measuring
it refuted it. All 66 books as `<Book> 3:16`, English into Russian under
numbers-only masking, and back again:

* 65 of 66 book names were translated by the model.
* **25 of them came back a different book, or not a book at all.** Job became
  `Работа` ("Work"), Lamentations `Пожалуйста` ("Please"), Ecclesiastes
  `Искусство` ("The Art"), and Joel, Obadiah, Nahum, Habakkuk and Haggai all
  collapsed into one word: `Иоанн`, "John".
* Hebrew and Arabic are worse. Unprotected, Chinese renders Deuteronomy as
  "Catholic" and Arabic renders Genesis as "the Bible".

A citation reading `Работа 3:16` is not a cosmetic defect. It is a wrong
scripture reference, stated with the same confidence as a right one, in a tool
built for Bible study - and undetectable downstream, because nothing in the
output records what the book used to be.

So the trade is made deliberately and in one direction. A reference left in
English is *untranslated*, which a reader can see and work around. A reference
the model has rewritten is *wrong*, and they cannot. Roughly 40 of the 65
Russian book names were previously coming out right; those are now English too,
and that is the price of the other 25 never being wrong.

Two smaller consequences fall out, both wanted:

* One placeholder per reference instead of three. Measured on 40 corpus lines
  into Hebrew, this leaves *less* English in the rest of the sentence - 4 lines
  affected fell to 1 - because a placeholder suppresses translation of the
  words beside it, and there are now fewer of them.
* A line that is nothing but a citation masks down to `@0@.` and is passed
  through untouched by `is_only_reference` below, instead of going to a model
  that hallucinates a sentence around it.

Restoring the book name *translated*, from a table, would beat both options.
That needs a real multilingual table of the 66 books. The model cannot be used
to build one, for the reason measured above.

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

import json
import logging
import re
from pathlib import Path
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

# Which book each of those tokens belongs to. `_BOOKS` above is only a *guard*
# - it answers "is this a citation at all" - and that was all it ever needed to
# do while references were held back in English. Naming the book in another
# language needs the stronger answer: which of the 66 is this.
#
# Split in two because eight books come in numbered pairs (or a trio), and the
# ordinal in front is what tells them apart. `2 Cor.` is Second Corinthians;
# `Cor.` alone is not a citation anyone writes.
_PLAIN_BOOKS: dict[str, tuple[str, ...]] = {
    "Genesis": ("genesis", "gen", "ge", "gn"),
    "Exodus": ("exodus", "exod", "exo", "ex"),
    "Leviticus": ("leviticus", "lev", "le", "lv"),
    "Numbers": ("numbers", "num", "nu", "nm"),
    "Deuteronomy": ("deuteronomy", "deut", "deu", "dt"),
    "Joshua": ("joshua", "josh", "jos"),
    "Judges": ("judges", "judg", "jdg"),
    "Ruth": ("ruth", "rth", "rut"),
    "Ezra": ("ezra", "ezr"),
    "Nehemiah": ("nehemiah", "neh"),
    "Esther": ("esther", "esth", "est"),
    "Job": ("job", "jb"),
    "Psalms": ("psalms", "psalm", "psa", "pss", "ps"),
    "Proverbs": ("proverbs", "prov", "pro", "prv"),
    "Ecclesiastes": ("ecclesiastes", "eccl", "ecc"),
    "Song of Solomon": ("song", "songs", "canticles"),
    "Isaiah": ("isaiah", "isa", "is"),
    "Jeremiah": ("jeremiah", "jer"),
    "Lamentations": ("lamentations", "lam"),
    "Ezekiel": ("ezekiel", "ezek", "eze"),
    "Daniel": ("daniel", "dan", "dn"),
    "Hosea": ("hosea", "hos"),
    "Joel": ("joel", "joe"),
    "Amos": ("amos", "am"),
    "Obadiah": ("obadiah", "obad", "oba"),
    "Jonah": ("jonah", "jon"),
    "Micah": ("micah", "mic"),
    "Nahum": ("nahum", "nah"),
    "Habakkuk": ("habakkuk", "hab"),
    "Zephaniah": ("zephaniah", "zeph"),
    "Haggai": ("haggai", "hag"),
    "Zechariah": ("zechariah", "zech", "zec"),
    "Malachi": ("malachi", "mal"),
    "Matthew": ("matthew", "matt", "mat", "mt"),
    "Mark": ("mark", "mrk", "mk"),
    "Luke": ("luke", "luk", "lk"),
    "Acts": ("acts", "act"),
    "Romans": ("romans", "rom", "ro"),
    "Galatians": ("galatians", "gal"),
    "Ephesians": ("ephesians", "eph"),
    "Philippians": ("philippians", "phil"),
    "Colossians": ("colossians", "col"),
    "Titus": ("titus", "tit"),
    "Philemon": ("philemon", "phlm"),
    "Hebrews": ("hebrews", "heb"),
    "James": ("james", "jas", "jam"),
    "Jude": ("jude", "jud"),
    "Revelation": ("revelation", "rev"),
}

# The base name of a numbered book. `John` is in both tables on purpose: with
# an ordinal it is one of the three epistles, without one it is the Gospel,
# which is the convention every citation in this corpus follows.
_NUMBERED_BOOKS: dict[str, tuple[str, ...]] = {
    "Samuel": ("samuel", "sam", "sa"),
    "Kings": ("kings", "kgs", "kin"),
    "Chronicles": ("chronicles", "chron", "chr"),
    "Corinthians": ("corinthians", "cor"),
    "Thessalonians": ("thessalonians", "thess", "thes"),
    "Timothy": ("timothy", "tim"),
    "Peter": ("peter", "pet", "pe"),
    "John": ("john", "jhn", "joh", "jn"),
}
_PLAIN_BOOKS["John"] = ("john", "jhn", "joh", "jn")

_TOKEN_TO_PLAIN = {
    token: name for name, tokens in _PLAIN_BOOKS.items() for token in tokens
}
_TOKEN_TO_NUMBERED = {
    token: name for name, tokens in _NUMBERED_BOOKS.items() for token in tokens
}

_WORD_ORDINALS = {
    "first": 1, "1st": 1, "1": 1,
    "second": 2, "2nd": 2, "2": 2,
    "third": 3, "3rd": 3, "3": 3,
}

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


# ------------------------------------------------- naming the book out loud

_TABLE: dict | None = None


def _table() -> dict:
    """The Wikidata book names, loaded once.

    A missing or broken table is not an error. Every reference simply stays in
    English, which is what happened before the table existed.
    """
    global _TABLE
    if _TABLE is None:
        path = Path(__file__).resolve().parent / "data" / "book_names.json"
        try:
            _TABLE = json.loads(path.read_text(encoding="utf-8"))["books"]
        except Exception:
            log.warning("no book-name table at %s; citations stay in English", path)
            _TABLE = {}
    return _TABLE


def identify(reference: str) -> str | None:
    """Which of the 66 books this reference names, or None.

    The ordinal has to be read together with the name: `Cor.` on its own does
    not identify a book, and returning "Corinthians" for it would be a guess.
    `John` without an ordinal is the Gospel, with one it is the epistle, which
    is how every citation in this corpus is written.
    """
    ordinal: int | None = None
    for word in re.findall(r"[A-Za-z]+|\d+", reference):
        low = word.lower()
        if ordinal is None and low in _WORD_ORDINALS:
            ordinal = _WORD_ORDINALS[low]
            continue
        if low in _TOKEN_TO_NUMBERED:
            if ordinal is None:
                return _TOKEN_TO_PLAIN.get(low)   # "John" alone is the Gospel
            return f"{ordinal} {_TOKEN_TO_NUMBERED[low]}"
        if low in _TOKEN_TO_PLAIN:
            return _TOKEN_TO_PLAIN[low]
    return None


def chapter_and_verse(reference: str) -> str:
    """The numbers of a reference, in the written `66:8,9` form.

    A spoken citation is normalised on the way through: "Psalm 66, verses 8 and
    9" becomes `66:8,9`. That is deliberate. Rendering it as words would need
    "chapter", "verse" and "and" in the target language, and those are exactly
    the words a model gets wrong beside a placeholder - the defect this whole
    table exists to remove. `66:8,9` needs no words at all and is read the same
    way in every language that uses Arabic numerals.
    """
    end = None
    for word in re.finditer(r"[A-Za-z]+", reference):
        if word.group(0).lower() in BOOK_NAMES:
            end = word.end()
    tail = reference[end:] if end is not None else reference

    if ":" in tail:                      # already written form; keep it
        return re.sub(r"\s+", "", tail).strip(",;.")

    numbers = list(re.finditer(r"\d{1,3}", tail))
    if not numbers:
        return ""
    out = numbers[0].group(0)
    for previous, current in zip(numbers, numbers[1:]):
        gap = tail[previous.end():current.start()]
        if previous is numbers[0]:
            separator = ":"              # the first number was the chapter
        elif re.search(r"through|to|[-–]", gap, re.IGNORECASE):
            separator = "-"
        else:
            separator = ","
        out += separator + current.group(0)
    return out


def localize(reference: str, language: str) -> str | None:
    """`2 Cor. 4:17,18` in `language`, or None if it cannot be named there.

    None is the useful answer when the table has no entry: the caller keeps the
    English, which is wrong-looking but not wrong. English itself returns None,
    because the table's own English is `Book of Job` where a citation wants
    `Job` - there is nothing to gain by rewriting a reference into the language
    it was already written in.
    """
    if not language or language == "en":
        return None
    book = identify(reference)
    if not book:
        return None
    label = _table().get(book, {}).get("labels", {}).get(language)
    if not label:
        return None
    return f"{label} {chapter_and_verse(reference)}".strip()


def mask(text: str, offset: int = 0) -> tuple[str, list[str]]:
    """Replace whole scripture references with placeholders.

    Returns the masked text and what was taken out, in order. Only spans that
    `find_references` recognised as a citation are touched; a year, a page
    number or a section number elsewhere in the line is left alone.
    """
    spans = find_references(text)
    if not spans:
        return text, []

    pieces: list[str] = []
    taken: list[str] = []
    cursor = 0
    for start, end in spans:
        pieces.append(text[cursor:start])
        pieces.append(PLACEHOLDER.format(offset + len(taken)))
        taken.append(text[start:end])
        cursor = end
    pieces.append(text[cursor:])
    return "".join(pieces), taken


def restore(
    text: str,
    references: Sequence[str],
    offset: int = 0,
    language: str | None = None,
) -> str:
    """Put the references back where the translation left their placeholders.

    A placeholder the model dropped is not silently forgiven: the reference is
    appended rather than lost, because a citation missing from a verse quotation
    is worse than one in the wrong place, and both are better than the model's
    own rendering of it.
    """
    if not references:
        return text

    # Named in the target language where the table can name it, and left in
    # English where it cannot. Never handed to the model, either way.
    def render(reference: str) -> str:
        return (localize(reference, language) or reference) if language else reference

    seen: set[int] = set()

    def put_back(match: "re.Match") -> str:
        index = int(match.group(1)) - offset
        if 0 <= index < len(references):
            seen.add(index)
            return render(references[index])
        return match.group(0)

    out = _PLACEHOLDER_RE.sub(put_back, text)

    missing = [render(ref) for i, ref in enumerate(references) if i not in seen]
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

    This is load-bearing now that the whole reference is masked, where under
    numbers-only masking it almost never fired. `Psalm 66, verses 8 and 9.`
    masks down to `@0@.`, and every file in this corpus opens and closes with
    a line like it.

    Such a line must not reach the model. Handed a placeholder and no sentence
    it invents one around it - `0 0 0 0` into Russian, `El 0@` into Spanish,
    both observed. The line is passed through untouched instead, which is also
    the right answer: there is nothing in it to translate.
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


def unprotect(
    texts: Sequence[str],
    taken: Sequence[Sequence[str]],
    language: str | None = None,
) -> list[str]:
    """Undo `protect`, text by text, naming the books in `language`."""
    return [
        restore(text, refs, language=language) if refs else text
        for text, refs in zip(texts, taken)
    ]
