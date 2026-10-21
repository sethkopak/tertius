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

It runs the app's own code - the same calls `jobs.py` makes, voice cloning
included - so what it measures is what the app does.

**The reference** is the Chinese translation in its spoken form
(`numbers.spell`, so `詩篇 66:8,9` is scored as 第六十六篇...), with
Traditional characters converted to Simplified on both sides. Whisper writes
Simplified, and madlad mixes the two, so without that every 書 heard as 书
would count as an error. That conversion needs OpenCC, which the app does not:

    .venv/Scripts/python.exe -m pip install --target PYLIB opencc-python-reimplemented==0.1.7

and pass `--pylib PYLIB`, or install it into the environment.

Results recorded so far are in STATUS.md, 2026-10-21: ten Manna files (the
default `--files`), 5.3% misheard at baseline and 3.2% after that day's fixes.
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


def speak(out, source, files, args):
    import torch
    from tertius.speech import Speaker, chunks_from_prose, speak_chunks, voice_for

    sp = Speaker(device="cuda")
    for i, stem in enumerate(files):
        if (out / f"{stem}.zh.spoken.wav").exists():
            continue
        r = pickle.loads((out / f"{stem}.result.pkl").read_bytes())
        prose = (out / f"{stem}.zh.txt").read_text(encoding="utf-8")
        chunks = chunks_from_prose(prose, sp.model_key, "neutral")
        scratch = tempfile.mkdtemp(prefix="harness-voice-")
        try:
            voice, _ = voice_for(source / f"{stem}.mp3", r, None, scratch)
            # Seeded per file, so two runs over unchanged text read it the
            # same way and a difference in score comes from a change.
            torch.manual_seed(1000 + i)
            speak_chunks(chunks, sp, "zh", out, stem, voice=voice, suffix=".zh.spoken", formats=[])
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        print("spoke", stem, flush=True)
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
        p = out / f"{stem}.heard{args.heard_tag}.txt"
        if p.exists():
            continue
        r = tr.transcribe(out / f"{stem}.zh.spoken.wav")
        p.write_text("".join(s.text for s in r.segments), encoding="utf-8")
        print("listened", stem, r.language, flush=True)
    tr.unload()
    free()


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
        return re.sub(r"[\W_a-zA-Z]+", "", cc.convert(text).translate(same))

    total_e = total_n = 0
    for stem in files:
        hp = out / f"{stem}.heard{args.heard_tag}.txt"
        if not hp.exists():
            continue
        ref = norm((out / f"{stem}.zh.txt").read_text(encoding="utf-8"), True)
        hyp = norm(hp.read_text(encoding="utf-8"), False)
        sm = difflib.SequenceMatcher(None, ref, hyp, autojunk=False)
        errors, lost = 0, []
        for op, i1, i2, j1, j2 in sm.get_opcodes():
            if op == "equal":
                continue
            errors += max(i2 - i1, j2 - j1)
            if op == "delete" and i2 - i1 >= 6:
                lost.append(ref[i1:i2])
        total_e += errors
        total_n += len(ref)
        print(f"{stem}  {errors / len(ref):6.1%}  of {len(ref):4d} chars  lost: "
              f"{' | '.join(lost) if lost else '-'}", flush=True)
    if total_n:
        print(f"ALL   {total_e / total_n:6.1%}  ({total_e}/{total_n})", flush=True)


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
