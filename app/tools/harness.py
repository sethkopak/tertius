"""Measure how well a reading can be understood, over many recordings.

English recording -> transcript -> translation -> reading -> what Whisper
hears back -> (optionally) that, translated back into English. Whisper stands
in for a listener; **every figure this prints is Whisper's, not a person's.**

Run from `app/`:

    .venv/Scripts/python.exe -X utf8 tools/harness.py OUT all --lang he --source DIR

`STAGE` is `transcribe`, `translate`, `speak`, `listen`, `score`, `back` or
`all`. Each stage runs across every file before the next starts, so each model
is loaded once and only one is on the GPU at a time. A stage skips files it has
already done, so an experiment can redo one stage and keep the rest: delete
`*.<lang>.spoken*.wav` to read again, or `listen --heard-tag _x --hotwords
"..."` to try a different Whisper hint without touching the readings. Copying
another run's `*.result.pkl` into OUT reuses its transcripts, so two languages
can start from the same English.

`--takes N` reads and listens to each file N times, each take seeded apart,
and scores the mean with every take's figure beside it. One reading per file
cannot tell half a point from take-to-take noise, which was about a point per
file for Chinese on 2026-10-22. The first take keeps the file names and seed a
one-take run uses, so an existing run is its first take; later takes add
`.t1`, `.t2`.

It runs the app's own code - the same calls `jobs.py` makes, voice cloning
included - so what it measures is what the app does.

**Chinese** (`--lang zh`, what `zh_harness.py` was): the share of the
reading's characters heard wrong, plus every stretch of six or more that never
made it into the audio. The reference is the translation in its spoken form
(`numbers.spell`), Traditional and Simplified folded together, which needs
OpenCC:

    .venv/Scripts/python.exe -m pip install --target PYLIB opencc-python-reimplemented==0.1.7

and pass `--pylib PYLIB`. Not counted (since 2026-10-22): 吗哪 heard as 玛纳 or
玛娜 - it is read as 玛哪 on purpose - and a known Whisper hallucination at the
very end of what was heard. `--raw` scores as before.

**Hebrew** (`--lang he`, 2026-10-26): the reference is the translation in
spoken form too. Both sides lose vowel points, cantillation, geresh,
punctuation and Latin, and final letters are folded (ך->כ...), since Whisper
writes Hebrew unpointed and none of that is heard. Three figures per file:
- **letters** - letters heard wrong, spaces ignored, so a one-letter prefix
  written apart (`ב תהילים`) or joined (`בתהילים`) is not an error. The one
  decisions rest on.
- **skeleton** - the same with every ו and י dropped except at the start of a
  word, so full and defective spellings (תהילים / תהלים) match. It also merges
  words a listener tells apart (הוא / היא), so it is shown, not used to decide.
- **sound** - the skeleton with letters modern Hebrew says alike made one
  (א/ע/ה, ח/כ, ט/ת, ק/כ, ב/ו, ס/ש) and א dropped like ו and י. Closest to
  what a listener gets wrong (2026-10-27): 39% of the misheard letters of the
  3.9% run were these spellings. Unpointed Hebrew cannot tell every vowel
  apart (`מן` is "man" and "min"), so it misses some real mishearings.
- **words** - word error rate, for reading; prefixes make it harsh.
A run of three or more reference words heard not at all is listed as lost.
Not counted, unless `--raw`: a trailing `תודה רבה`, Whisper's text after the
last word, and the gender of a number word (`שנים עשר` / `שתים עשרה`).

**Arabic** (`--lang ar`, 2026-10-27): the reference is the translation in
spoken form. Both sides lose short vowels, shadda, sukun, tanwin, tatweel,
punctuation and Latin, and spellings that sound alike are folded (أ/إ/آ->ا,
ى->ي, ة->ه); Arabic-Indic digits count as digits. **letters** (spaces
ignored) decides; **words** is shown.

`back` translates what was heard into English with the app's translator and
scores it against the English transcript: chrF (character n-grams 1-6, beta
2), scripture references come back right, and whether the title's month
survived.
"""

from __future__ import annotations

import argparse
import difflib
import gc
import logging
import pickle
import re
import shutil
import sys
import tempfile
import unicodedata
from collections import Counter
from pathlib import Path

APP = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(APP / "src"))

# Ten Manna recordings spread across the year, none of them used to tune
# anything. 0101 is left out on purpose: every fix before 2026-10-21 was
# tuned on it.
FILES = ["0120", "0226", "0403", "0510", "0616", "0723", "0829", "1005", "1111", "1218"]


def free():
    import torch

    gc.collect()
    torch.cuda.empty_cache()


def transcribe(out, source, files, args):
    from tertius.config import TranscriptionOptions
    from tertius.transcribe import WhisperTranscriber

    tr = WhisperTranscriber(TranscriptionOptions(language=None))
    for stem in files:
        p = out / f"{stem}.result.pkl"
        if p.exists():
            continue
        r = tr.transcribe(source / f"{stem}.mp3")
        p.write_bytes(pickle.dumps(r))
        print("transcribed", stem, r.language, len(r.segments), flush=True)
    tr.unload()
    free()


def translate(out, source, files, args):
    from tertius.translate import Translator, translate_outputs

    t = Translator(args.translator, device="cuda")
    for stem in files:
        p = out / f"{stem}.{args.lang}.txt"
        if p.exists():
            continue
        r = pickle.loads((out / f"{stem}.result.pkl").read_bytes())
        _, tr = translate_outputs(
            r, source / f"{stem}.mp3", out / "scratch", [], t, args.lang, for_speech=True
        )
        p.write_text(tr.prose, encoding="utf-8")
        print("translated", stem, flush=True)
    t.unload()
    free()


def take_tags(args):
    """File-name tags for each take: "" for the first, so a run made before
    `--takes` existed is that run's first take, then ".t1", ".t2"..."""
    return [""] + [f".t{t}" for t in range(1, args.takes)]


def speak(out, source, files, args):
    import torch
    from tertius.speech import Speaker, chunks_from_prose, speak_chunks, voice_for

    sp = Speaker(device="cuda")
    for i, stem in enumerate(files):
        tags = [t for t in take_tags(args)
                if not (out / f"{stem}.{args.lang}.spoken{t}.wav").exists()]
        if not tags:
            continue
        r = pickle.loads((out / f"{stem}.result.pkl").read_bytes())
        prose = (out / f"{stem}.{args.lang}.txt").read_text(encoding="utf-8")
        chunks = chunks_from_prose(prose, sp.model_key, "neutral")
        scratch = tempfile.mkdtemp(prefix="harness-voice-")
        try:
            voice, _ = voice_for(source / f"{stem}.mp3", r, None, scratch)
            for tag in tags:
                take = take_tags(args).index(tag)
                # Seeded per file and take, so two runs over unchanged text
                # read it the same way and a difference in score comes from a
                # change; the first take keeps the seed it always had.
                torch.manual_seed(1000 + i + 1000 * take)
                speak_chunks(chunks, sp, args.lang, out, stem, voice=voice,
                             suffix=f".{args.lang}.spoken{tag}", formats=[])
                print("spoke", stem, f"take {take + 1}", flush=True)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
    sp.unload()
    free()


def listen(out, source, files, args):
    import tertius.transcribe as T
    from tertius.config import TranscriptionOptions

    if args.hotwords is not None:
        # "" means no hint at all.
        T.PUNCTUATION_HINTS = {args.lang: args.hotwords}
    tr = T.WhisperTranscriber(TranscriptionOptions(language=None))
    for stem in files:
        for tag in take_tags(args):
            p = out / f"{stem}.heard{args.heard_tag}{tag}.txt"
            if p.exists():
                continue
            r = tr.transcribe(out / f"{stem}.{args.lang}.spoken{tag}.wav")
            p.write_text("".join(s.text for s in r.segments), encoding="utf-8")
            # Whisper detects the language itself, as it does in the app; a
            # reading it takes for another language is a result too.
            print("listened", stem, tag or "take 1", r.language, flush=True)
    tr.unload()
    free()


# Whisper's own text on the silence after speech, as found at the end of these
# readings. Only ones actually seen here; it has others.
HALLUCINATIONS = {
    "zh": ("请不吝点赞订阅转发打赏支持明镜与点点栏目", "谢谢"),
    # Hebrew's are taken off in `hebrew_scorer`, as words.
    "he": (),
}


def drop_trailing_hallucinations(ref: str, hyp: str, language: str) -> str:
    """`hyp` without known Whisper hallucinations at its end, unless `ref` ends so."""
    stripped = True
    while stripped:
        stripped = False
        for phrase in HALLUCINATIONS.get(language, ()):
            if hyp.endswith(phrase) and not ref.endswith(phrase):
                hyp = hyp[: -len(phrase)]
                stripped = True
    return hyp


def errors_in(ref, hyp, lost_at):
    """Edits between two sequences, and every deleted run of `lost_at` or more."""
    sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
    errors, lost = 0, []
    for op, i1, i2, j1, j2 in sm.get_opcodes():
        if op == "equal":
            continue
        errors += max(i2 - i1, j2 - j1)
        if op == "delete" and i2 - i1 >= lost_at:
            lost.append(ref[i1:i2])
    return errors, lost


# Chinese scoring, unless `--raw`. Both exclusions were scorer artifacts, not
# things a listener would get wrong, and together they were 22 of 77 misheard
# characters in one run and 20 of 103 in another (2026-10-22) - more than the
# differences being measured.
MANNA = re.compile("[吗玛][哪纳娜]")


def chinese_scorer(args):
    """`norm(text, spoken_form) -> {figure: sequence}` and its lost threshold."""
    if args.pylib:
        sys.path.insert(0, args.pylib)
    try:
        from opencc import OpenCC
    except ImportError:
        sys.exit("scoring Chinese needs OpenCC; see the docstring at the top of this file")
    from tertius.numbers import _chinese, spell

    cc = OpenCC("t2s")
    # Three ways of writing "he"; which one the model picked is not a mishearing.
    same = str.maketrans("祂她它", "他他他")

    def norm(text, spoken_form):
        if spoken_form:
            text = spell(text, "zh")
        text = re.sub(
            r"\d+",
            lambda m: _chinese(int(m.group())) if int(m.group()) <= 9999 else m.group(),
            text,
        )
        text = re.sub(r"[\W_a-zA-Z]+", "", cc.convert(text).translate(same))
        if not args.raw:
            # 吗哪 is read as 玛哪 on purpose (speech.SPOKEN_AS), and Whisper
            # writes what it hears: 玛纳, 玛娜. Not a mishearing of the title.
            text = MANNA.sub("吗哪", text)
        return {"chars": text}

    return norm, {"chars": 6}


# Everything Hebrew text carries that is not a letter heard: vowel points,
# cantillation, meteg, rafe, dagesh, shin/sin dots (U+0591-U+05C7, maqaf and
# sof pasuq among them).
_POINTS = re.compile(r"[֑-ׇ]")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")
_NOT_HEBREW = re.compile(r"[^א-ת ]+")


HEBREW_HALLUCINATION = ["תודה", "רבה"]

# Letters modern Hebrew says alike, mapped together for the `sound` figure.
# Of the 3.9% run's misheard letters, 39% were these and ו/י/א written or not:
# read right, spelled Whisper's way (2026-10-27).
_SAME_SOUND = str.maketrans({"ע": "א", "ה": "א", "ח": "כ", "ט": "ת", "ק": "כ",
                             "ב": "ו", "ס": "ש"})

# A number's gender, folded: `שנים עשר` and `שתים עשרה` are both twelve.
# Whisper writes most numbers it hears as digits, which are spelled back here
# in `num2words`' default feminine, while a reference may be read masculine
# (`פרק שנים עשר`); without this, every chapter heard right was an error
# (2026-10-26). Final letters are already folded when this applies.
_NUMBER_GENDER = {
    "אחד": "אחת", "שנימ": "שתימ", "שניימ": "שתימ", "שתיימ": "שתימ",
    "שלושה": "שלוש", "ארבעה": "ארבע", "חמישה": "חמש", "שישה": "שש",
    "שבעה": "שבע", "תשעה": "תשע", "עשרה": "עשר",
}


def _fold_number(word: str) -> str:
    """A number word in one gender, keeping a one-letter prefix (ו, ל...)."""
    if word in _NUMBER_GENDER:
        return _NUMBER_GENDER[word]
    if word[1:] in _NUMBER_GENDER and word[0] in "ובלמהכש":
        return word[0] + _NUMBER_GENDER[word[1:]]
    return word


def hebrew_scorer(args):
    from tertius.numbers import spell

    def norm(text, spoken_form):
        # Both sides spelled: the reading's digits are spoken as words, and
        # Whisper writes some numbers it hears as digits.
        text = spell(unicodedata.normalize("NFC", text), "he")
        # A maqaf or hyphen joins words; a space keeps them two.
        text = _POINTS.sub(lambda m: " " if m.group() == "־" else "", text)
        text = _NOT_HEBREW.sub(" ", text.replace("-", " ")).translate(_FINALS)
        words = text.split()
        if not spoken_form and not args.raw:
            # "Thank you very much": Whisper's text after the last reference
            # in 3 of 30 baseline readings (2026-10-26). No text ends so.
            while words[-len(HEBREW_HALLUCINATION):] == HEBREW_HALLUCINATION:
                words = words[: -len(HEBREW_HALLUCINATION)]
        if not args.raw:
            words = [_fold_number(w) for w in words]
        # ו and י are often only a vowel letter, written or left out by
        # spelling convention; at the start of a word they are a consonant or
        # the prefix "and".
        skeleton = "".join(w[0] + re.sub("[וי]", "", w[1:]) for w in words)
        sound = "".join(
            w[0] + re.sub("[ויא]", "", w[1:]) for w in (w.translate(_SAME_SOUND) for w in words)
        )
        return {"letters": "".join(words), "skeleton": skeleton, "sound": sound,
                "words": words}

    return norm, {"letters": 10**9, "skeleton": 10**9, "sound": 10**9, "words": 3}


# Everything Arabic text carries that is not a letter heard: short vowels,
# tanwin, shadda, sukun, dagger alef (U+064B-U+065F, U+0670), Quranic marks
# (U+06D6-U+06ED) and tatweel.
_HARAKAT = re.compile(r"[ً-ٰٟۖ-ۭـ]")
# Spellings Whisper and the translator choose between for one sound: the
# hamza's seat on alef, alef maqsura for ya, ta marbuta for ha.
_AR_SPELLINGS = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ى": "ي", "ة": "ه"})
_AR_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩۰۱۲۳۴۵۶۷۸۹", "01234567890123456789")
_NOT_ARABIC = re.compile(r"[^ء-ي ]+")


def arabic_scorer(args):
    from tertius.numbers import spell

    def norm(text, spoken_form):
        # Both sides spelled, as for Hebrew; Whisper writes either kind of digit.
        # NFKC: madlad writes some lam-alifs as one presentation form (ﻻ).
        text = unicodedata.normalize("NFKC", text).translate(_AR_DIGITS)
        text = _HARAKAT.sub("", spell(text, "ar"))
        words = _NOT_ARABIC.sub(" ", text.translate(_AR_SPELLINGS)).split()
        return {"letters": "".join(words), "words": words}

    return norm, {"letters": 10**9, "words": 3}


SCORERS = {"zh": chinese_scorer, "he": hebrew_scorer, "ar": arabic_scorer}


def score(out, source, files, args):
    norm, lost_at = SCORERS[args.lang](args)
    figures = list(lost_at)
    # Per take, so the spread between takes is visible next to the mean.
    tags = take_tags(args)
    take_e = {f: [0] * len(tags) for f in figures}
    take_n = {f: [0] * len(tags) for f in figures}
    for stem in files:
        ref = norm((out / f"{stem}.{args.lang}.txt").read_text(encoding="utf-8"), True)
        per_take = {f: [] for f in figures}
        lost_all = []
        for t, tag in enumerate(tags):
            hp = out / f"{stem}.heard{args.heard_tag}{tag}.txt"
            if not hp.exists():
                continue
            hyp = norm(hp.read_text(encoding="utf-8"), False)
            for f in figures:
                h = hyp[f]
                if not args.raw and isinstance(h, str):
                    h = drop_trailing_hallucinations(ref[f], h, args.lang)
                errors, lost = errors_in(ref[f], h, lost_at[f])
                per_take[f].append(errors / len(ref[f]))
                lost_all += [" ".join(x) if isinstance(x, list) else x for x in lost]
                take_e[f][t] += errors
                take_n[f][t] += len(ref[f])
        if not per_take[figures[0]]:
            continue
        cells = []
        for f in figures:
            p = per_take[f]
            takes = "  ".join(f"{x:5.1%}" for x in p) if len(p) > 1 else ""
            cells.append(f"{f} {sum(p) / len(p):6.1%} of {len(ref[f]):4d}  {takes}")
        print(f"{stem}  {'   '.join(cells)}  lost: "
              f"{' | '.join(lost_all) if lost_all else '-'}", flush=True)
    for f in figures:
        done = [(e, n) for e, n in zip(take_e[f], take_n[f]) if n]
        if done:
            total_e, total_n = sum(e for e, _ in done), sum(n for _, n in done)
            spread = "  ".join(f"{e / n:5.1%}" for e, n in done) if len(done) > 1 else ""
            print(f"ALL {f:8s} {total_e / total_n:6.1%}  ({total_e}/{total_n})  {spread}",
                  flush=True)


def chrf(hyp: str, ref: str, n_max: int = 6, beta: float = 2.0) -> float:
    """chrF (Popovic 2015): character n-grams 1..6, whitespace removed,
    precision and recall averaged over n, then F-beta with beta 2."""
    h, r = "".join(hyp.split()), "".join(ref.split())
    precisions, recalls = [], []
    for n in range(1, n_max + 1):
        hc = Counter(h[i:i + n] for i in range(len(h) - n + 1))
        rc = Counter(r[i:i + n] for i in range(len(r) - n + 1))
        if not hc or not rc:
            continue
        match = sum((hc & rc).values())
        precisions.append(match / sum(hc.values()))
        recalls.append(match / sum(rc.values()))
    if not precisions:
        return 0.0
    p, rr = sum(precisions) / len(precisions), sum(recalls) / len(recalls)
    if p + rr == 0:
        return 0.0
    return 100 * (1 + beta**2) * p * rr / (beta**2 * p + rr)


_ROMAN = re.compile(r"\b(III|II|I)(?= [A-Z][a-z])")


def references(text):
    """Every scripture reference in English text, as `book chapter:verse`."""
    from tertius.scripture import chapter_and_verse, find_references, identify

    # madlad writes "I Timothy" as often as "1 Timothy".
    text = _ROMAN.sub(lambda m: str(len(m.group(1))), text)
    return [f"{identify(text[a:b])} {chapter_and_verse(text[a:b])}"
            for a, b in find_references(text)]


def back(out, source, files, args):
    """What was heard, into English with the app's translator, then scored."""
    from tertius.translate import Translator, prose_sentences, sentences_of

    t = None
    for stem in files:
        for tag in take_tags(args):
            p = out / f"{stem}.back{args.heard_tag}{tag}.en.txt"
            heard = out / f"{stem}.heard{args.heard_tag}{tag}.txt"
            if p.exists() or not heard.exists():
                continue
            if t is None:
                t = Translator(args.back_translator or args.translator, device="cuda")
            text = heard.read_text(encoding="utf-8").strip()
            # As the app would have it: stops Whisper left out are put back.
            en = t.translate(sentences_of([text], args.lang), "en", source_language=args.lang)
            p.write_text("\n".join(x.strip() for x in en if x.strip()) + "\n",
                         encoding="utf-8")
            print("back", stem, tag or "take 1", flush=True)
    if t is not None:
        t.unload()
        free()

    right = wanted = titles = readings = 0
    scores = []
    for stem in files:
        english = " ".join(prose_sentences(
            pickle.loads((out / f"{stem}.result.pkl").read_bytes())))
        want = references(english)
        month = re.search(r"Manna for (\w+)", english, re.IGNORECASE)
        per_take = []
        for tag in take_tags(args):
            p = out / f"{stem}.back{args.heard_tag}{tag}.en.txt"
            if not p.exists():
                continue
            en = p.read_text(encoding="utf-8")
            got = references(en)
            ok = sum(min(want.count(w), got.count(w)) for w in set(want))
            right += ok
            wanted += len(want)
            readings += 1
            if month and month.group(1).lower() in en.lower():
                titles += 1
            per_take.append(chrf(en, english))
            if ok < len(want):
                print(f"  {stem}{tag or ''}  want {want}  got {got}")
        if per_take:
            scores += per_take
            print(f"{stem}  chrF {sum(per_take) / len(per_take):5.1f}  "
                  + "  ".join(f"{x:5.1f}" for x in per_take), flush=True)
    if scores:
        print(f"BACK  chrF {sum(scores) / len(scores):5.1f}  references right "
              f"{right}/{wanted}  title month kept {titles}/{readings}", flush=True)


STAGES = {
    "transcribe": transcribe,
    "translate": translate,
    "speak": speak,
    "listen": listen,
    "score": score,
    "back": back,
}


def main(default_lang: str | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", help="folder for every intermediate file and result")
    ap.add_argument("stage", choices=[*STAGES, "all"])
    ap.add_argument("--lang", choices=sorted(SCORERS), default=default_lang,
                    required=default_lang is None, help="language the reading is in")
    ap.add_argument("--source", type=Path, help="folder holding the <stem>.mp3 recordings")
    ap.add_argument("--files", nargs="+", default=FILES, help="recording stems to use")
    ap.add_argument("--translator", default="madlad400-3B", help="translation model key")
    ap.add_argument("--back-translator", default=None,
                    help="model for the back stage; the --translator by default")
    ap.add_argument("--heard-tag", default="", help="suffix for a listen/score variant")
    ap.add_argument("--hotwords", default=None, help='Whisper hint for listen; "" for none')
    ap.add_argument("--pylib", default=None, help="extra folder on sys.path holding OpenCC")
    ap.add_argument("--takes", type=int, default=1,
                    help="read and listen to each file this many times; "
                         "scores are the mean, with each take's shown")
    ap.add_argument("--raw", action="store_true",
                    help="count what scoring otherwise leaves out (Chinese: 玛纳 "
                         "for 吗哪, trailing hallucinations)")
    args = ap.parse_args()

    stages = list(STAGES) if args.stage == "all" else [args.stage]
    if args.source is None and any(s in ("transcribe", "translate", "speak") for s in stages):
        ap.error("--source is needed to transcribe, translate or speak")

    logging.basicConfig(level=logging.WARNING, format="%(name)s: %(message)s")
    logging.getLogger("tertius").setLevel(logging.INFO)

    out = Path(args.out)
    out.mkdir(parents=True, exist_ok=True)
    for stage in stages:
        STAGES[stage](out, args.source, args.files, args)


if __name__ == "__main__":
    main()
