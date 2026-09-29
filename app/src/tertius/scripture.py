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


# Hebrew writes its one-letter prepositions and conjunctions as part of the next
# word - `בתהילים`, "in Psalms" - and the model, handed `in @0@`, writes `ב @0@`
# with a space, which put back reads `ב תהילים`: visibly wrong to a Hebrew
# reader (seen on the hosted m2m100, 2026-09-29).
#
# A standalone prefix is one of בכלמשה, or ו on its own or in front of one of
# them (`וב`, "and in"). Standalone, because nothing Hebrew may come before it:
# `של` ("of") and `מה` ("what") are words that happen to start with those
# letters, and the lookbehind is what leaves them alone. Hebrew has no
# one-letter words for this to mistake.
_HEBREW_LETTER = "א-ת"
_HE_DETACHED_PREFIX = re.compile(
    rf"(?<![{_HEBREW_LETTER}])(ו?[בכלמשה]|ו)\s+(?=@\d+@)"
)
# ב, כ and ל absorb the definite article: "in the Epistle" is `באיגרת`, not
# `בהאיגרת`. Named rather than inferred from a leading ה, because a leading ה is
# not always the article - `הושע`, Hosea, begins with one as part of the name,
# and dropping it would write `בושע`. These two are every label in the table
# whose first word carries the article (checked 2026-09-29).
_HE_ARTICLE_WORDS = ("הבשורה", "האיגרת")


def _after_hebrew_prefix(before: str, rendered: str) -> str:
    """Fit a restored reference to a Hebrew prefix written straight before it."""
    if not before or not re.match(rf"[{_HEBREW_LETTER}]", before[-1]):
        return rendered
    if rendered and not re.match(rf"[{_HEBREW_LETTER}]", rendered[0]):
        # A name the table could not give in Hebrew stays in English, and a
        # Hebrew prefix on a foreign word takes a hyphen: `ב-Psalm 66:8`.
        return "-" + rendered
    if before[-1] in "בכלה" and rendered.split(" ", 1)[0] in _HE_ARTICLE_WORDS:
        return rendered[1:]
    return rendered


# Russian declines the book's name after a preposition, and the table gives the
# nominative: the model writes `в @0@` ("in") and put back that read
# `в Псалтирь` where Russian needs `в Псалтири` (seen 2026-09-29).
#
# Only the leading words of a label ever change - the head noun, and an ordinal
# in front of it; everything after (`пророка Исаии`, `к Римлянам`) is already a
# fixed genitive or phrase. So this is a table of those words rather than a
# morphology library: twelve of them cover all 66 labels (checked 2026-09-29).
# Forms in the order genitive, dative, accusative, instrumental, prepositional.
_RU_CASES = ("gen", "dat", "acc", "ins", "prep")
_RU_FORMS = {
    "книга": ("книги", "книге", "книгу", "книгой", "книге"),
    "послание": ("послания", "посланию", "послание", "посланием", "послании"),
    "евангелие": ("евангелия", "евангелию", "евангелие", "евангелием", "евангелии"),
    "второзаконие": ("второзакония", "второзаконию", "второзаконие", "второзаконием", "второзаконии"),
    "откровение": ("откровения", "откровению", "откровение", "откровением", "откровении"),
    "псалтирь": ("псалтири", "псалтири", "псалтирь", "псалтирью", "псалтири"),
    "песнь": ("песни", "песни", "песнь", "песнью", "песни"),
    "плач": ("плача", "плачу", "плач", "плачем", "плаче"),
    "деяния": ("деяний", "деяниям", "деяния", "деяниями", "деяниях"),
    "первая": ("первой", "первой", "первую", "первой", "первой"),
    "вторая": ("второй", "второй", "вторую", "второй", "второй"),
    "третья": ("третьей", "третьей", "третью", "третьей", "третьей"),
    "четвёртая": ("четвёртой", "четвёртой", "четвёртую", "четвёртой", "четвёртой"),
}
# `1-е послание`, `1-я Паралипоменон`: the ordinal is a digit with its ending,
# and it is the ending that declines.
_RU_NUMBERED = {
    "е": ("го", "му", "е", "м", "м"),  # neuter: 1-е послание
    "я": ("й", "й", "ю", "й", "й"),  # feminine: 1-я (книга) Паралипоменон
}
# The case each preposition takes before a book - the ones whose case does not
# depend on the verb. `на`, `за` and `под` do, and are read with the verb in
# `_RU_TWO_CASE` below. `с` is taken as "with" (instrumental) rather than "from"
# (genitive): with a book it is nearly always "compare with", "agrees with".
_RU_PREPOSITION_CASE = {
    **dict.fromkeys(("в", "во", "о", "об", "обо", "при"), "prep"),
    **dict.fromkeys(("из", "от", "до", "у", "для", "без", "после", "около", "из-за", "среди"), "gen"),
    **dict.fromkeys(("к", "ко", "по"), "dat"),
    **dict.fromkeys(("с", "со", "над", "перед", "между"), "ins"),
    **dict.fromkeys(("про", "через"), "acc"),
}
_RU_WORD_BEFORE = re.compile(r"(?:^|[^а-яёА-ЯЁ-])([а-яёА-ЯЁ-]+)\s+$")

# A book straight after a verb that takes it as a direct object wants the
# accusative: `Сравнить Книга Иова` is `Сравнить Книгу Иова`. The case comes
# from the verb, so only verbs known to govern the accusative are recognized,
# and a name after anything else stays in the nominative - which is right when
# it is the subject (`Это Книга Иова`, a sentence that opens with the book).
#
# The stems are the verbs the hosted model actually wrote before a citation,
# probed 2026-09-29 (сравнить, читайте, рассмотрим, цитирует, помните,
# изучать), and their plain equivalents (open, mention). A stem alone would also
# catch nouns built on it - `изучение`, "study", wants the genitive - so the
# word must not end like a verbal noun, and must not be reflexive
# (`сравнивается` takes no object at all).
_RU_ACCUSATIVE_VERB = re.compile(
    r"^(?:сравн|чит|прочит|прочт|перечит|рассмотр|рассматрив|"
    r"цитир|процитир|помн|вспомн|вспомина|запомн|изуч|откр|упомина|упомян)"
)
_RU_VERBAL_NOUN = re.compile(r"(?:ени|ани|ти)(?:е|я|ю|ем|и|й|ям|ями|ях)$")
_RU_REFLEXIVE = re.compile(r"(?:ся|сь)$")


# на, за and под each take two cases, and the verb decides which - so for these
# three the words before the preposition are read too. Every stem here is one
# the hosted model actually wrote in front of the preposition when probed on
# 2026-09-29, with the case Russian gives it:
#
#   на   посмотрите/обратите внимание/указывает/полагается/рассчитывать на
#        -> accusative (a direction or an object: "look at", "rely on"), which
#        is also the default; основан/сосредоточьтесь/откройте Библию на
#        -> prepositional ("based on", "focus on", open *at* a place).
#   за   следует/стоит за -> instrumental ("follows", "stands behind");
#        слава Богу за -> accusative ("thanks for"). No default.
#   под  подпадает под -> accusative ("falls under"); стоим под ->
#        instrumental ("stand under"). No default.
#
# A за or под whose verb is not recognized is left in the nominative: a wrong
# case is no better than the table's own form.
_RU_TWO_CASE = {
    "на": (("prep", ("основан", "основыва", "базир", "построен", "сосредоточ", "откр", "останов")), "acc"),
    "за": (("acc", ("благодар", "спасибо", "слава", "хвал")), ("ins", ("след", "стои", "стоя", "скрыва"))),
    "под": (("acc", ("подпада", "попада", "подпаст", "попаст")), ("ins", ("стои", "стоя", "наход", "жив"))),
}
# How far back to look for the verb: `Откройте свою Библию на` puts two words
# between the verb and the preposition.
_RU_VERB_WINDOW = 3


def _russian_two_case(preposition: str, earlier: Sequence[str]) -> str | None:
    """The case after на/за/под, read from the words before it."""
    first, second = _RU_TWO_CASE[preposition]
    stems_by_case = [first] + ([second] if isinstance(second, tuple) else [])
    for word in reversed(earlier[-_RU_VERB_WINDOW:]):
        word = word.lower()
        for case, stems in stems_by_case:
            if word.startswith(stems):
                return case
    # Only на has a default; see the table above.
    return second if isinstance(second, str) else None


def _russian_case_before(word: str, earlier: Sequence[str] = ()) -> str | None:
    """The case a book takes after `word`, or None to leave it nominative.

    `earlier` are the words before `word`, for the prepositions whose case
    depends on the verb.
    """
    word = word.lower()
    if word in _RU_TWO_CASE:
        return _russian_two_case(word, earlier)
    case = _RU_PREPOSITION_CASE.get(word)
    if case:
        return case
    if (
        _RU_ACCUSATIVE_VERB.match(word)
        and not _RU_VERBAL_NOUN.search(word)
        and not _RU_REFLEXIVE.search(word)
    ):
        return "acc"
    return None


def _decline_ru_word(word: str, case: str) -> str | None:
    """One word in `case`, keeping its capital; None if the table does not know it."""
    i = _RU_CASES.index(case)
    numbered = re.fullmatch(r"(\d+)-([ея])", word)
    if numbered:
        return f"{numbered.group(1)}-{_RU_NUMBERED[numbered.group(2)][i]}"
    forms = _RU_FORMS.get(word.lower())
    if not forms:
        return None
    form = forms[i]
    return form[:1].upper() + form[1:] if word[:1].isupper() else form


def _after_russian_preposition(before: str, rendered: str) -> str:
    """Put a restored book name in the case the word before it governs."""
    found = _RU_WORD_BEFORE.search(before)
    earlier = re.findall(r"[а-яёА-ЯЁ-]+", before[: found.start(1)]) if found else []
    case = _russian_case_before(found.group(1), earlier) if found else None
    if not case:
        return rendered
    words = rendered.split(" ")
    first = _decline_ru_word(words[0], case)
    if first is None:
        # Not a name from the table - an English one it could not give, say.
        return rendered
    words[0] = first
    # An ordinal carries its noun with it: `Первой книге`, `1-м послании`.
    ordinal = words[0][:1].isdigit() or words[0].lower() in {
        _RU_FORMS[k][_RU_CASES.index(case)] for k in ("первая", "вторая", "третья", "четвёртая")
    }
    if ordinal and len(words) > 1:
        second = _decline_ru_word(words[1], case)
        if second is not None:
            words[1] = second
    return " ".join(words)


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

    hebrew = (language or "").lower() == "he"
    russian = (language or "").lower() == "ru"
    if hebrew:
        # `ב @0@` -> `ב@0@`: the prefix is joined before anything is put back,
        # so `put_back` can see it and fit the name to it.
        text = _HE_DETACHED_PREFIX.sub(r"\1", text)

    seen: set[int] = set()

    def put_back(match: "re.Match") -> str:
        index = int(match.group(1)) - offset
        if 0 <= index < len(references):
            seen.add(index)
            rendered = render(references[index])
            if hebrew:
                rendered = _after_hebrew_prefix(match.string[: match.start()], rendered)
            elif russian:
                rendered = _after_russian_preposition(match.string[: match.start()], rendered)
            return rendered
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


# A masked source that ends on a citation and then its sentence's stop:
# `Compare @0@ with @1@.` The stop is captured; anything after it (a closing
# quote or bracket) is allowed but not carried over.
_ENDS_ON_CITATION = re.compile(r"@\d+@([.!?…]+)[\"'”’)\]]*\s*$")
# A translation that ends on a bare placeholder, with nothing after it.
_ENDS_ON_PLACEHOLDER = re.compile(r"@\d+@\s*$")

# Where a language writes its sentence stop differently. The same scripts
# `alignment._SENTENCE_END` splits on - anything not here gets the source's own
# stop, which is what the model writes for the rest.
_STOPS = {
    "zh": {".": "。", "!": "！", "?": "？"},
    "ja": {".": "。", "!": "！", "?": "？"},
    "ar": {"?": "؟"},
    "fa": {"?": "؟"},
    "ur": {".": "۔", "?": "؟"},
    "hi": {".": "।"},
    "mr": {".": "।"},
    "ne": {".": "।"},
    "bn": {".": "।"},
    "hy": {".": "։"},
}


def keep_final_stop(source: str, translated: str, language: str | None = None) -> str:
    """Put back a sentence's full stop when the model dropped it after a citation.

    Measured on the hosted m2m100 on 2026-09-29: `Compare @0@ with @1@.` came
    back as `Сравнить @0@ с @1@`, and the same in Spanish and Hebrew - the stop
    straight after the last placeholder is dropped, and a `.txt` meant to be one
    sentence per line gets a line with no ending. Both arguments are *masked*
    text: this runs before `restore`, while the placeholder still marks where
    the citation sits.

    Deliberately narrow. Only when the source ends citation-then-stop and the
    translation ends on the bare placeholder: a model that rephrased and ended
    the sentence another way has made its own choice, and is left alone.
    """
    wanted = _ENDS_ON_CITATION.search(source or "")
    if not wanted or not _ENDS_ON_PLACEHOLDER.search(translated or ""):
        return translated
    stop = wanted.group(1)
    table = _STOPS.get((language or "").lower(), {})
    stop = "".join(table.get(ch, ch) for ch in stop)
    return translated.rstrip() + stop


def unprotect(
    texts: Sequence[str],
    taken: Sequence[Sequence[str]],
    language: str | None = None,
    sources: Sequence[str] | None = None,
) -> list[str]:
    """Undo `protect`, text by text, naming the books in `language`.

    `sources` are the masked texts that were translated, one per text. Given,
    a stop the model dropped after a closing citation is put back first - see
    `keep_final_stop`.
    """
    out = []
    for i, (text, refs) in enumerate(zip(texts, taken)):
        if refs and sources is not None and i < len(sources):
            text = keep_final_stop(sources[i], text, language)
        out.append(restore(text, refs, language=language) if refs else text)
    return out
