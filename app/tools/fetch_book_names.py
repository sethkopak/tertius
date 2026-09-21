"""Fetch the names of the 66 books of the Bible from Wikidata, in every
language the translator can reach.

Run this to regenerate `src/tertius/data/book_names.json`. It is the only part
of Tertius that touches the network outside a model download, and it is a
*build* step: the table ships as data and the app never calls Wikidata.

    python tools/fetch_book_names.py

**Why a table at all.** A translation model cannot be trusted with a book name.
Measured, all 66 books as `<Book> 3:16` English into Russian and back: 25 came
back a different book or not a book at all - Job as "Work", Lamentations as
"Please", and five minor prophets all as "John". So the names come from a
curated source or they do not get translated.

**Why Wikidata.** It is CC0, so nothing about shipping the table constrains
Tertius' MIT licence, and it carries one curated label per item per language.

**The Q-ids below are not guessed.** They are every instance of "book of the
Bible" (Q29154430), which returns exactly 67 items: these 66, plus
Q12358883, an Estonian-only duplicate with no English label, which is dropped.
Each id was checked against its English label before being written down.

**Labels are taken verbatim, including the descriptive part.** Wikidata's
Russian for Job is `Книга Иова` - "Book of Job" - where a citation would
normally read `Иов`. Stripping that is tempting and is not done: the word for
"book" differs per language, and in Russian what is left behind is a genitive
(`Иова`) rather than the nominative a citation wants. The aliases are worse -
Russian Revelation carries twenty of them, including `Светопреставление`
("doomsday") and an adjective - so there is no safe rule for picking one.
A slightly long citation that names the right book in the right script beats a
short one that names the wrong book.
"""

from __future__ import annotations

import json
import sys
import urllib.parse
import urllib.request
from datetime import date
from pathlib import Path

ENDPOINT = "https://query.wikidata.org/sparql"
USER_AGENT = "tertius-bible-book-names/1.0 (https://github.com/sethkopak/tertius)"

OUT = Path(__file__).resolve().parents[1] / "src" / "tertius" / "data" / "book_names.json"

# Canonical citation name -> Wikidata item. Protestant canon, in canonical
# order, which is also the order the table is written in.
BOOKS: tuple[tuple[str, str], ...] = (
    ("Genesis", "Q9184"), ("Exodus", "Q9190"), ("Leviticus", "Q41490"),
    ("Numbers", "Q43099"), ("Deuteronomy", "Q42614"), ("Joshua", "Q47680"),
    ("Judges", "Q81240"), ("Ruth", "Q80038"),
    ("1 Samuel", "Q1975029"), ("2 Samuel", "Q209719"),
    ("1 Kings", "Q131066"), ("2 Kings", "Q209746"),
    ("1 Chronicles", "Q9813916"), ("2 Chronicles", "Q209720"),
    ("Ezra", "Q131635"), ("Nehemiah", "Q131640"), ("Esther", "Q131068"),
    ("Job", "Q4577"), ("Psalms", "Q41064"), ("Proverbs", "Q4579"),
    ("Ecclesiastes", "Q131072"), ("Song of Solomon", "Q51670"),
    ("Isaiah", "Q131458"), ("Jeremiah", "Q131590"), ("Lamentations", "Q179058"),
    ("Ezekiel", "Q178390"), ("Daniel", "Q80115"), ("Hosea", "Q184030"),
    ("Joel", "Q131643"), ("Amos", "Q174677"), ("Obadiah", "Q174753"),
    ("Jonah", "Q178819"), ("Micah", "Q178076"), ("Nahum", "Q179755"),
    ("Habakkuk", "Q179760"), ("Zephaniah", "Q188563"), ("Haggai", "Q178338"),
    ("Zechariah", "Q179769"), ("Malachi", "Q51675"),
    ("Matthew", "Q392302"), ("Mark", "Q107388"), ("Luke", "Q39939"),
    ("John", "Q36766"), ("Acts", "Q40309"), ("Romans", "Q48203"),
    ("1 Corinthians", "Q80355"), ("2 Corinthians", "Q123808"),
    ("Galatians", "Q128620"), ("Ephesians", "Q408673"),
    ("Philippians", "Q51613"), ("Colossians", "Q131095"),
    ("1 Thessalonians", "Q131115"), ("2 Thessalonians", "Q131107"),
    ("1 Timothy", "Q131180"), ("2 Timothy", "Q131489"),
    ("Titus", "Q131493"), ("Philemon", "Q131104"), ("Hebrews", "Q128608"),
    ("James", "Q131097"), ("1 Peter", "Q131119"), ("2 Peter", "Q131178"),
    ("1 John", "Q131101"), ("2 John", "Q131453"), ("3 John", "Q131462"),
    ("Jude", "Q131466"), ("Revelation", "Q42040"),
)

# Every language m2m100-418M can translate into. Written out rather than
# imported so this script stays runnable on its own, and checked against
# `supported_target_languages("m2m100-418M")` by the test suite.
LANGUAGES = (
    "af am ar ast az ba be bg bn br bs ca ceb cs cy da de el en es et fa ff fi "
    "fr fy ga gd gl gu ha he hi hr ht hu hy id ig ilo is it ja jv ka kk km kn "
    "ko lb lg ln lo lt lv mg mk ml mn mr ms my ne nl no ns oc or pa pl ps pt "
    "ro ru sd si sk sl so sq sr ss su sv sw ta th tl tn tr uk ur uz vi wo xh "
    "yi yo zh zu"
).split()

# Where the translator's code for a language is not the code Wikidata files it
# under. Each target is tried in order and the first hit wins.
#
# Without this, Norwegian came back with zero of the 66 books: m2m100 calls it
# `no`, and Wikidata splits it into Bokmal and Nynorsk. Northern Sotho is the
# same shape - `ns` to the translator, `nso` to Wikidata.
ALIASES = {
    "no": ("no", "nb", "nn"),
    "ns": ("ns", "nso"),
    "zh": ("zh", "zh-hans", "zh-hant"),
}


def wikidata_codes() -> list[str]:
    """Every code to ask for, including the aliases."""
    codes: list[str] = []
    for code in LANGUAGES:
        for candidate in ALIASES.get(code, (code,)):
            if candidate not in codes:
                codes.append(candidate)
    return codes


def ask(query: str) -> dict:
    url = ENDPOINT + "?" + urllib.parse.urlencode({"query": query})
    request = urllib.request.Request(
        url,
        headers={"Accept": "application/sparql-results+json", "User-Agent": USER_AGENT},
    )
    with urllib.request.urlopen(request, timeout=180) as response:
        return json.load(response)


def main() -> int:
    ids = " ".join(f"wd:{qid}" for _name, qid in BOOKS)
    langs = ", ".join(f'"{code}"' for code in wikidata_codes())
    query = (
        "SELECT ?b ?lang ?label WHERE { "
        f"VALUES ?b {{ {ids} }} "
        "?b rdfs:label ?label . "
        "BIND(LANG(?label) AS ?lang) "
        f"FILTER(?lang IN ({langs})) }}"
    )
    print(f"asking Wikidata for {len(BOOKS)} books in {len(LANGUAGES)} languages...")
    data = ask(query)

    raw: dict[str, dict[str, str]] = {qid: {} for _n, qid in BOOKS}
    for row in data["results"]["bindings"]:
        qid = row["b"]["value"].rsplit("/", 1)[1]
        raw[qid][row["lang"]["value"]] = row["label"]["value"]

    # Collapse the alias codes back onto the codes the translator uses.
    by_qid: dict[str, dict[str, str]] = {}
    for _name, qid in BOOKS:
        found = raw[qid]
        resolved: dict[str, str] = {}
        for code in LANGUAGES:
            for candidate in ALIASES.get(code, (code,)):
                if candidate in found:
                    resolved[code] = found[candidate]
                    break
        by_qid[qid] = resolved

    # An item that came back with no English label means the id is wrong, or
    # Wikidata moved it. Fail loudly rather than write a table with a hole.
    missing = [n for n, qid in BOOKS if "en" not in by_qid[qid]]
    if missing:
        print(f"ERROR: no English label for {missing}", file=sys.stderr)
        return 1

    table = {
        "source": "Wikidata (https://www.wikidata.org), CC0 1.0",
        "fetched": date.today().isoformat(),
        "generator": "tools/fetch_book_names.py",
        "books": {
            name: {"qid": qid, "labels": dict(sorted(by_qid[qid].items()))}
            for name, qid in BOOKS
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(table, ensure_ascii=False, indent=1, sort_keys=False) + "\n",
        encoding="utf-8",
    )

    counts = {c: sum(1 for _n, q in BOOKS if c in by_qid[q]) for c in LANGUAGES}
    full = [c for c, n in counts.items() if n == len(BOOKS)]
    print(f"wrote {OUT} ({OUT.stat().st_size:,} bytes)")
    print(f"{len(full)} of {len(LANGUAGES)} languages have all 66 books")
    thin = sorted((n, c) for c, n in counts.items() if n < len(BOOKS))
    if thin:
        print("incomplete:", ", ".join(f"{c}={n}" for n, c in thin))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
