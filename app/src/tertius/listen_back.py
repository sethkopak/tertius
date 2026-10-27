"""Listening to each generated chunk, to catch text the voice model left out.

Chatterbox sometimes ends a chunk early and cleanly, so nothing sounds wrong
and the abrupt-ending check (`tail_ratio`) passes: the words are simply not
there. Measured on 2026-10-20, ten Manna readings in Chinese: the last chunk
of 1005 ended `...恐怕你们心里疲乏乏力 。 " 希伯來書 第十二章第三节.`, and the
reading stopped after the closing quote. On 2026-10-19 one take in three of
0101 left out a whole clause.

So a small Whisper on the CPU transcribes each chunk, and a stretch of the
chunk's text that it did not hear sends the chunk back for another take.
`base` was chosen by measurement: on 1005, 0120 and 1111 it found the
missing reference and nothing else, as `small` did, at 7-18 s per file
against 19-26 s. On the CPU because the GPU is full of the voice model while
this runs.

Chinese, and Hebrew since 2026-10-26: the languages this was measured on.

**Hebrew listens with `small`.** `base` mishears 12-27% of Hebrew letters in
these readings (large-v3-turbo about 4%). Run over thirty whole Hebrew
readings with two real drops in them - 0120's `בהתחלה זה מאוד רך`, 0616's
`האיגרת אל העברים 12:11` - `base` found both and raised three false alarms;
`small` (9-18% misheard) found both and raised one, at 12 s against 4 s per
minute of reading. Two more apparent drops were Whisper large mishearing
them, not Chatterbox leaving them out. A chapter-and-verse count like
Chinese's is not used: `small` missed `פרק` or `פסוק` in readings that had
them all.
"""

from __future__ import annotations

import difflib
import logging
import re
from typing import Sequence

log = logging.getLogger(__name__)

# The model that listens to each language. See the module docstring.
LISTENER_MODELS = {"zh": "base", "he": "small"}
LANGUAGES = frozenset(LISTENER_MODELS)
# A stretch of the text this long, unheard, counts as left out. Shorter gaps
# are what a small model mishears anyway. Chinese in characters; Hebrew in
# letters, the spaces taken out - 12 is about three words.
MIN_MISSING = {"zh": 6, "he": 12}
WHISPER_RATE = 16_000

_NOT_TEXT = re.compile(r"[\W_a-zA-Z]+")
_DIGITS = re.compile(r"\d+")
# A chapter or verse as `numbers.spell` says one: 第十二章, 第二十三篇, 第五节.
_CHAPTER_OR_VERSE = re.compile(r"第[〇零一二三四五六七八九十百千]+[章篇节節]")
# What `base` writes for a chapter or verse that was read, 2026-10-22: 第12张
# and 第13張 for 章 (zhāng), 第二十三片 for Psalm's 篇 (piān). Counted as heard,
# or every Psalm and most chapters cost the chunk five takes for nothing.
_SAME_SOUND = str.maketrans("张張片節", "章章篇节")


def names_a_reference(stretches: Sequence[str]) -> bool:
    """Is any of these left-out stretches part of a scripture reference?

    Every reference cut short on 2026-10-21/22 lost a chapter or a verse with
    it: 來書第十二章, 詩篇第二十三篇第五节, 希伯來書第十二章第十一节.
    """
    # Hebrew references are read `פרק ..., פסוק ...` (numbers.py).
    return any(
        _CHAPTER_OR_VERSE.search(s) or "פרק" in s or "פסוק" in s for s in stretches
    )


def missing_references(spoken: str, heard: str) -> list[str]:
    """Chapters and verses of `spoken` heard fewer times than they are said.

    A cut reference loses too little for `missing_text` to see: on 2026-10-22
    0616 read 希伯來書 12:11 without 第十二章, four characters, in 3 of 6
    readings, and listening back passed all of them: `base` heard the book
    name wrong too (西部来书, 西伯来输), so 希伯來書第十二章 against 西部来书 was a
    misheard word to `missing_text`, not a gap. So each 第...章, 第...篇 and
    第...节 is counted on its own, whatever its length.
    """
    said = _normalize(spoken).replace("節", "节")
    got = _normalize(heard).translate(_SAME_SOUND)
    out = []
    for ref in dict.fromkeys(m.group() for m in _CHAPTER_OR_VERSE.finditer(said)):
        short = len(re.findall(re.escape(ref), said)) - len(re.findall(re.escape(ref), got))
        out += [ref] * max(short, 0)
    return out


# Hebrew: vowel points and cantillation (the text spoken carries them), and
# the final letter forms, which Whisper may or may not write.
_HEBREW_POINTS = re.compile(r"[֑-ׇ]")
_NOT_HEBREW = re.compile(r"[^א-ת]+")
_FINALS = str.maketrans("ךםןףץ", "כמנפצ")


def _normalize(text: str, language: str = "zh") -> str:
    if language == "he":
        from .numbers import spell

        # Whisper writes numbers it hears as digits; the reading says words.
        text = spell(_HEBREW_POINTS.sub("", text), "he")
        return _NOT_HEBREW.sub("", text).translate(_FINALS)

    from .numbers import _chinese

    text = _DIGITS.sub(
        lambda m: _chinese(int(m.group())) if int(m.group()) <= 9999 else m.group(),
        text,
    )
    return _NOT_TEXT.sub("", text)


def missing_text(spoken: str, heard: str, language: str = "zh") -> list[str]:
    """Stretches of `spoken` that are absent from `heard`.

    A replacement counts only when the spoken side is more than twice the
    heard side: a Traditional character heard back as its Simplified form, or
    a misheard word, is a one-for-one swap and not an omission.
    """
    said, got = _normalize(spoken, language), _normalize(heard, language)
    least = MIN_MISSING[language]
    matcher = difflib.SequenceMatcher(None, said, got, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if i2 - i1 < least:
            continue
        if op == "delete" or (op == "replace" and i2 - i1 > 2 * (j2 - j1)):
            out.append(said[i1:i2])
    return out


def added_text(spoken: str, heard: str, language: str = "zh") -> list[str]:
    """Stretches of `heard` with no counterpart in `spoken`: babble.

    The mirror of `missing_text`. On 2026-10-21 Chatterbox babbled in the
    middle of 0403 - Whisper heard 这里采万,依台万,台万,采万,采万,采万,采万, none
    of it in the text - and listening back, which looked only for what was
    left out, passed it. It was most of that file's 18% misheard.
    """
    said, got = _normalize(spoken, language), _normalize(heard, language)
    least = MIN_MISSING[language]
    matcher = difflib.SequenceMatcher(None, said, got, autojunk=False)
    out = []
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        if j2 - j1 < least:
            continue
        if op == "insert" or (op == "replace" and j2 - j1 > 2 * (i2 - i1)):
            out.append(got[j1:j2])
    return out


def _resample(samples: Sequence[float], rate: int):
    import numpy

    audio = numpy.asarray(samples, dtype=numpy.float32)
    if rate == WHISPER_RATE or not len(audio):
        return audio
    length = int(len(audio) * WHISPER_RATE / rate)
    positions = numpy.linspace(0, len(audio) - 1, length)
    return numpy.interp(positions, numpy.arange(len(audio)), audio).astype(numpy.float32)


class Listener:
    """A CPU Whisper per language, loaded on first use, that never fails a reading."""

    def __init__(self):
        self._models: dict = {}
        self._unavailable: set[str] = set()

    def _load(self, language: str):
        name = LISTENER_MODELS[language]
        if name not in self._models and name not in self._unavailable:
            try:
                from huggingface_hub import snapshot_download
                from faster_whisper import WhisperModel

                from .transcribe import MODEL_FILE_PATTERNS, resolve_repo_id

                # Downloaded by `Speaker.load` at job start. Here only what is
                # already on disk is used, so a reading never stops to fetch it.
                folder = snapshot_download(
                    resolve_repo_id(name),
                    allow_patterns=MODEL_FILE_PATTERNS,
                    local_files_only=True,
                )
                self._models[name] = WhisperModel(folder, device="cpu", compute_type="int8")
            except Exception as exc:
                log.info("not listening back to the reading: %s", exc)
                self._unavailable.add(name)
        return self._models.get(name)

    def check(
        self, spoken: str, samples: Sequence[float], rate: int, language: str
    ) -> tuple[list[str], list[str]]:
        """`(left out, added)` for a chunk; both empty when nothing could tell."""
        if language not in LANGUAGES:
            return [], []
        model = self._load(language)
        if model is None:
            return [], []
        try:
            segments, _ = model.transcribe(
                _resample(samples, rate), language=language, beam_size=1,
                vad_filter=False, condition_on_previous_text=False,
            )
            heard = "".join(segment.text for segment in segments)
        except Exception:
            log.debug("listening back failed", exc_info=True)
            return [], []
        missing = missing_text(spoken, heard, language)
        # A chapter or verse already inside a left-out stretch is not counted twice.
        missing += [
            ref for ref in missing_references(spoken, heard)
            if not any(ref in stretch.replace("節", "节") for stretch in missing)
        ]
        return missing, added_text(spoken, heard, language)

    def unload(self) -> None:
        self._models = {}


def ensure_model(on_progress=None, languages=None) -> None:
    """Fetch the listeners at job start. Not fatal: no listener, no check.

    Only those `languages` need, when the job says which it will read: `small`
    is 464 MB, and a job reading only Chinese has no use for it. Every
    language's when it does not, since the reading may then be in any.
    """
    from .transcribe import ensure_model_downloaded

    wanted = LISTENER_MODELS if languages is None else {
        language: LISTENER_MODELS[language]
        for language in languages if language in LISTENER_MODELS
    }
    for name in dict.fromkeys(wanted.values()):
        try:
            ensure_model_downloaded(name, on_progress)
        except Exception as exc:
            log.info("could not fetch the listen-back model %s: %s", name, exc)
