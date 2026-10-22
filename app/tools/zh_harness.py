"""Measure how well a Chinese reading can be understood, over many recordings.

English recording -> transcript -> Chinese translation -> Chinese reading ->
what Whisper hears back. Whisper stands in for a Chinese listener. The score
is the share of the reading's characters it heard wrong, plus every stretch of
six or more characters that never made it into the audio at all.

Run from `app/`:

    .venv/Scripts/python.exe -X utf8 tools/zh_harness.py OUT all --source DIR

`STAGE` is `transcribe`, `translate`, `speak`, `listen`, `score` or `all`.
Each stage runs across every file before the next starts, so each model is
loaded once and only one is on the GPU at a time. A stage skips files it has
already done, so an experiment can redo one stage and keep the rest: delete
`*.zh.spoken.wav` to read again, or `listen --heard-tag _x --hotwords "..."`
to try a different Whisper hint without touching the readings.

`--takes N` reads and listens to each file N times, each take seeded apart,
and scores the mean with every take's figure beside it. One reading per file
cannot tell half a point from take-to-take noise, which was about a point per
file on 2026-10-22. The first take keeps the file names and seed a one-take
run uses, so an existing run is its first take; later takes add `.t1`, `.t2`.

It runs the app's own code - the same calls `jobs.py` makes, voice cloning
included - so what it measures is what the app does.

**The reference** is the Chinese translation in its spoken form
(`numbers.spell`, so `詩篇 66:8,9` is scored as 第六十六篇...), with
Traditional characters converted to Simplified on both sides. Whisper writes
Simplified, and madlad mixes the two, so without that every 書 heard as 书
would count as an error. That conversion needs OpenCC, which the app does not:

    .venv/Scripts/python.exe -m pip install --target PYLIB opencc-python-reimplemented==0.1.7

and pass `--pylib PYLIB`, or install it into the environment.

**Two things are not counted** (since 2026-10-22): 吗哪 heard as 玛纳 or 玛娜 -
it is read as 玛哪 on purpose - and a known Whisper hallucination at the very
end of what was heard (谢谢, 请不吝点赞订阅...), Whisper's text for trailing
silence. `--raw` scores as before, for comparing with older figures.

Results are in STATUS.md: ten Manna files (the default `--files`), 5.3%
misheard at baseline on 2026-10-21, raw scoring, and the runs since.
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
        p = out / f"{stem}.zh.txt"
        if p.exists():
            continue
        r = pickle.loads((out / f"{stem}.result.pkl").read_bytes())
        _, tr = translate_outputs(
            r, source / f"{stem}.mp3", out / "scratch", [], t, "zh", for_speech=True
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
        tags = [t for t in take_tags(args) if not (out / f"{stem}.zh.spoken{t}.wav").exists()]
        if not tags:
            continue
        r = pickle.loads((out / f"{stem}.result.pkl").read_bytes())
        prose = (out / f"{stem}.zh.txt").read_text(encoding="utf-8")
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
                speak_chunks(chunks, sp, "zh", out, stem, voice=voice,
                             suffix=f".zh.spoken{tag}", formats=[])
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
        T.PUNCTUATION_HINTS = {"zh": args.hotwords}
    tr = T.WhisperTranscriber(TranscriptionOptions(language=None))
    for stem in files:
        for tag in take_tags(args):
            p = out / f"{stem}.heard{args.heard_tag}{tag}.txt"
            if p.exists():
                continue
            r = tr.transcribe(out / f"{stem}.zh.spoken{tag}.wav")
            p.write_text("".join(s.text for s in r.segments), encoding="utf-8")
            print("listened", stem, tag or "take 1", r.language, flush=True)
    tr.unload()
    free()


# Scoring, unless `--raw`. Both were scorer artifacts, not things a listener
# would get wrong, and together they were 22 of 77 misheard characters in one
# run and 20 of 103 in another (2026-10-22) - more than the differences being
# measured.
MANNA = re.compile("[吗玛][哪纳娜]")
# Whisper's own text on the silence after speech, as found at the end of these
# readings. Only ones actually seen here; it has others.
HALLUCINATIONS = ("请不吝点赞订阅转发打赏支持明镜与点点栏目", "谢谢")


def drop_trailing_hallucinations(ref: str, hyp: str) -> str:
    """`hyp` without known Whisper hallucinations at its end, unless `ref` ends so."""
    stripped = True
    while stripped:
        stripped = False
        for phrase in HALLUCINATIONS:
            if hyp.endswith(phrase) and not ref.endswith(phrase):
                hyp = hyp[: -len(phrase)]
                stripped = True
    return hyp


def score(out, source, files, args):
    if args.pylib:
        sys.path.insert(0, args.pylib)
    try:
        from opencc import OpenCC
    except ImportError:
        sys.exit("scoring needs OpenCC; see the docstring at the top of this file")
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
        return text

    def errors_in(ref, hyp):
        sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
        errors, lost = 0, []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            errors += max(i2 - i1, j2 - j1)
            if op == "delete" and i2 - i1 >= 6:
                lost.append(ref[i1:i2])
        return errors, lost

    # Per take, so the spread between takes is visible next to the mean.
    tags = take_tags(args)
    take_e = [0] * len(tags)
    take_n = [0] * len(tags)
    for stem in files:
        ref = norm((out / f"{stem}.zh.txt").read_text(encoding="utf-8"), True)
        per_take, lost_all = [], []
        for t, tag in enumerate(tags):
            hp = out / f"{stem}.heard{args.heard_tag}{tag}.txt"
            if not hp.exists():
                continue
            hyp = norm(hp.read_text(encoding="utf-8"), False)
            if not args.raw:
                hyp = drop_trailing_hallucinations(ref, hyp)
            errors, lost = errors_in(ref, hyp)
            per_take.append(errors / len(ref))
            lost_all += lost
            take_e[t] += errors
            take_n[t] += len(ref)
        if not per_take:
            continue
        mean = sum(per_take) / len(per_take)
        takes = "  ".join(f"{p:5.1%}" for p in per_take) if len(per_take) > 1 else ""
        print(f"{stem}  {mean:6.1%}  of {len(ref):4d} chars  {takes}  lost: "
              f"{' | '.join(lost_all) if lost_all else '-'}", flush=True)
    done = [(e, n) for e, n in zip(take_e, take_n) if n]
    if done:
        total_e, total_n = sum(e for e, _ in done), sum(n for _, n in done)
        spread = "  ".join(f"{e / n:5.1%}" for e, n in done) if len(done) > 1 else ""
        print(f"ALL   {total_e / total_n:6.1%}  ({total_e}/{total_n})  {spread}", flush=True)


STAGES = {
    "transcribe": transcribe,
    "translate": translate,
    "speak": speak,
    "listen": listen,
    "score": score,
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", help="folder for every intermediate file and result")
    ap.add_argument("stage", choices=[*STAGES, "all"])
    ap.add_argument("--source", type=Path, help="folder holding the <stem>.mp3 recordings")
    ap.add_argument("--files", nargs="+", default=FILES, help="recording stems to use")
    ap.add_argument("--translator", default="madlad400-3B", help="translation model key")
    ap.add_argument("--heard-tag", default="", help="suffix for a listen/score variant")
    ap.add_argument("--hotwords", default=None, help='Chinese Whisper hint for listen; "" for none')
    ap.add_argument("--pylib", default=None, help="extra folder on sys.path holding OpenCC")
    ap.add_argument("--takes", type=int, default=1,
                    help="read and listen to each file this many times; "
                         "scores are the mean, with each take's shown")
    ap.add_argument("--raw", action="store_true",
                    help="score as before 2026-10-22: 玛纳 for 吗哪 and trailing "
                         "hallucinations count as errors")
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
